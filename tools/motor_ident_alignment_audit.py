"""Offline six-shot alignment audit. Reads saved files only; never accesses MCU.

The ideal RL sensitivity below is explicitly a hypothesis, not latch evidence
or an inductance estimate. Original receipts and qualification remain untouched.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics as st
import struct
from foc_path_profile_report import symbols

ROOT=Path(__file__).resolve().parents[1]
ELF=ROOT/'foc2_app_a/build/MotorParameterIdentificationLAdmissionDiagnostic/foc2.elf'
SHA='13b237a70625218bfddb8924b13022a95410b1313f14547238036de2f9e5c786'
ELF_SHA='08f4fe731598162155fd34cb4432a208d5e6cd5a40dabde2c68185c152b06ea0'


def ideal_rl_residual(rows,mode,rs=.78,fraction=.5):
    """No fabricated verified=True. Minimum residual under an ideal timing MODEL."""
    if len(rows)!=32 or any(b['seq']!=a['seq']+1 or not 45<=b['us']-a['us']<=55
                           for a,b in zip(rows,rows[1:])):
        return dict(status='NOT_EVALUATED_MISSING_INTERVAL_VOLTAGE')
    i_key,v_key=('id','vd') if mode=='LD' else ('iq','vq')
    pairs=[(rows[k][i_key],rows[k+1][i_key],rows[k-2][v_key],rows[k-1][v_key],
            (rows[k+1]['us']-rows[k]['us'])*1e-6) for k in range(2,len(rows)-1)]
    lo=3*st.mean(p[-1] for p in pairs);hi=(rows[-1]['us']-rows[0]['us'])*.5e-6
    def mse(tau):
        terms=[]
        for i,j,old,new,dt in pairs:
            a=math.exp(-dt/tau);b=math.exp(-(1-fraction)*dt/tau)
            terms.append((j-a*i-(b-a)*old/rs-(1-b)*new/rs,(1-a)/rs))
        bias=sum(y*x for y,x in terms)/sum(x*x for _,x in terms)
        return st.mean((y-bias*x)**2 for y,x in terms)
    grid=[lo*(hi/lo)**(k/319) for k in range(320)]
    best=min(range(320),key=lambda k:mse(grid[k]))
    rms=math.sqrt(mse(grid[best]));span=max(r[i_key] for r in rows)-min(r[i_key] for r in rows)
    limit=min(.005,.15*span)
    return dict(status='UNQUALIFIED_IDEAL_RL_HYPOTHESIS_ONLY',fraction=fraction,
        command_lag_model=2,minimum_prediction_rms_a=rms,original_rms_limit_a=limit,
        exceeds_original_rms_gate=rms>limit,boundary_minimum=best<3 or best>316,
        inductance_h=None,warning='No physical latch/aperture verification, no measured phase voltage')


def audit(parent_path):
    if hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA:raise ValueError('Exact ELF required')
    sym=symbols(ELF);parent=json.loads(parent_path.read_text('utf-8'));points=[]
    if parent.get('image_sha256')!=SHA or parent.get('elf_sha256')!=ELF_SHA:
        raise ValueError('Exact batch image identity required')
    keys='us seq pending_before id_ref iq_ref id iq vd vq angle speed mode status reason reserved'.split()
    for path in parent['points']:
        r=json.loads(Path(path).read_text('utf-8'));raw=Path(r['ram_capture']).read_bytes()
        flash=Path(r['final_capture']).read_bytes()
        if (len(raw)!=0x20000 or hashlib.sha256(raw).hexdigest()!=r['ram_sha256'] or
            hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
            hashlib.sha256(flash[0x8000:0x8000+215156]).hexdigest()!=SHA):
            raise ValueError('Saved same-session Flash/RAM hash mismatch')
        address,size=sym['motor_ident'];offset=address-0x20000000
        if size!=1740:raise ValueError('Exact diagnostic ABI required')
        n=struct.unpack_from('<I',raw,offset+1536)[0]
        if n>32:raise ValueError('Bounded rows required')
        rows=[dict(zip(keys,struct.unpack_from('<3I8f4B',raw,offset+k*48))) for k in range(n)]
        if rows!=r['ident_run']['rows']:raise ValueError('JSON does not match binary rows')
        paddr,psize=sym['foc_pwm_write_profile']
        if psize!=128:raise ValueError('Exact probe ABI required')
        w=struct.unpack_from('<32I',raw,paddr-0x20000000)
        clock=raw[sym['clock_certified'][0]-0x20000000]
        current,voltage=('id','vd') if r['axis']=='LD' else ('iq','vq')
        changes=[b['us']-a['us'] for a,b in zip(rows,rows[1:])]
        gap_count=sum(b['seq']!=a['seq']+1 for a,b in zip(rows,rows[1:]))
        pre=[x[current] for x in rows if x['us']<100000]
        post=[x[current] for x in rows if x['us']>=100000]
        points.append(dict(axis=r['axis'],repeat=r['repeat'],receipt=path,n=n,
            seq_gaps=gap_count,dt_min_us=min(changes),dt_max_us=max(changes),
            pending_source_mismatches=sum(x['pending_before']!=x['seq']-1 for x in rows),
            pre_n=len(pre),pre_current_std_a=st.pstdev(pre) if pre else None,
            post_n=len(post),post_current_std_a=st.pstdev(post) if post else None,
            max_adjacent_current_change_a=max(abs(b[current]-a[current]) for a,b in zip(rows,rows[1:])),
            geometry=r['ident_run']['geometry'],clock_certified=bool(clock),
            lite_probe=dict(successful_commits=w[0],min_margin_ticks=w[5],
                detailed_points_captured=any(w[8:24]),detailed_geometry_captured=any(w[24:32]),
                note='Lite path increments points after stores, not legacy writes field'),
            hypothesis=[ideal_rl_residual(rows,r['axis'],fraction=f) for f in
                (.5,4250/8498,4258/8498)]))
    return dict(offline_only=True,firmware_changed=False,hardware_access=False,
        rs_assumption_ohm=.78,rs_qualified=False,ld=None,lq=None,points=points,
        inferred_timing=dict(timer_hz=170000000,adc_hz=42500000,arr=4249,ccr4=4184,
            trigger_to_top_us=65/170,sample_hold_end_after_trigger_us=[56/170,64/170],
            sample_hold_end_before_top_us=[1/170,9/170],
            aperture_end_to_bottom_us=[4250/170,4258/170],
            period_using_2arr_us=8498/170,fraction_bound=[4250/8498,4258/8498],
            status='STATIC_GEOMETRY_PLUS_DATASHEET_BOUND_NOT_WAVEFORM_MEASUREMENT',
            model='ADC(k)..ADC(k+1): old command(k-2), then at bottom command(k-1)',
            note='UEV also occurs at TOP; commit requires DIR down, so current stores target BOTTOM'),
        scope_note='No fit qualification or PI write; theoretical fraction not installed as verified evidence')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('batch',type=Path);a=p.parse_args()
    print(json.dumps(audit(a.batch),indent=2))


if __name__=='__main__':main()
