"""Offline-only L sample admission. Keep timestamps AND full voltage history.

Reject isolated current observations, never replace/interpolate them. A skipped
current can be bridged only when every intervening voltage command is recorded.
No fault clear, hardware access, firmware/PI write or fabricated timing proof.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics as st
import struct
from functools import lru_cache
import motor_identification_report as original
from foc_path_profile_report import symbols

ROOT=Path(__file__).resolve().parents[1]
MIN_SPIKE_A=.015
MAD_MULTIPLIER=3*1.4826
MIN_KEEP_FRACTION=.70
MIN_CURRENT_SAMPLES=16
MIN_MODEL_INTERVALS=16


def select_samples(run):
    # Original same-session safety/metadata and hard data checks remain first.
    rows=original.guard(run)
    if run['mode'] not in ('LD','LQ'):raise original.Insufficient('L axis required')
    current='id' if run['mode']=='LD' else 'iq'
    rejected=[]
    for k in range(2,len(rows)-2):
        w=rows[k-2:k+3]
        # Do not call a missing sample a neighbour or filter across a command step.
        if any(b['seq']!=a['seq']+1 for a,b in zip(w,w[1:])):continue
        if any(abs(x['vd']-w[0]['vd'])>1e-7 or abs(x['vq']-w[0]['vq'])>1e-7 for x in w):continue
        # Delay model uses two preceding commands; protect step onset as well.
        if k<4 or any(abs(rows[j]['vd']-rows[k]['vd'])>1e-7 or
                      abs(rows[j]['vq']-rows[k]['vq'])>1e-7 for j in range(k-4,k+3)):continue
        vals=[r[current] for r in w];med=st.median(vals)
        threshold=max(MIN_SPIKE_A,MAD_MULTIPLIER*st.median(abs(x-med) for x in vals))
        x=rows[k][current];left=rows[k-1][current];right=rows[k+1][current]
        if ((x-left)*(x-right)>0 and abs(x-left)>threshold and abs(x-right)>threshold and
            abs(x-med)>threshold):
            rejected.append(dict(index=k,seq=rows[k]['seq'],us=rows[k]['us'],
                current_a=x,local_median_a=med,threshold_a=threshold,
                reason='ISOLATED_CURRENT_OBSERVATION_OUTLIER_NOT_HARDWARE_FAULT'))
    indices=[k for k in range(len(rows)) if k not in {r['index'] for r in rejected}]
    if len(indices)<max(MIN_CURRENT_SAMPLES,math.ceil(MIN_KEEP_FRACTION*len(rows))):
        raise original.Insufficient('Too few usable samples after explicit rejection')
    return rows,indices,rejected


def available_intervals(rows,indices):
    """Measured endpoint indices plus recorded command/time segments; no fake i."""
    lookup={r['seq']:k for k,r in enumerate(rows)};good=[];excluded=[]
    for a,b in zip(indices,indices[1:]):
        parts=[];why=None
        for seq in range(rows[a]['seq'],rows[b]['seq']):
            need=(seq-2,seq-1,seq,seq+1)
            if any(s not in lookup for s in need):why='MISSING_RECORDED_VOLTAGE_OR_TIME';break
            old,new,start,end=(lookup[s] for s in need)
            dt=rows[end]['us']-rows[start]['us']
            if not 45<=dt<=55:why='UNQUALIFIED_PHYSICAL_INTERVAL_TIMESTAMP';break
            if rows[start]['pending_before']!=seq-1 or rows[end]['pending_before']!=seq:
                why='PENDING_SOURCE_CHAIN_NOT_EXPLAINED';break
            parts.append((old,new,dt*1e-6))
        if why:excluded.append(dict(from_seq=rows[a]['seq'],to_seq=rows[b]['seq'],reason=why))
        else:good.append((a,b,parts))
    return good,excluded


def fit_observations(run,rs=.78,fraction=None):
    if not math.isfinite(rs) or rs<=0:raise ValueError('Positive explicit Rs required')
    rows,indices,rejected=select_samples(run)
    intervals,excluded=available_intervals(rows,indices)
    out=dict(raw_recorded=len(rows),accepted_current_samples=len(indices),rejected_current_samples=len(rejected),
        rejected=rejected,usable_model_intervals=len(intervals),excluded_intervals=excluded,
        accepted_seq=[rows[k]['seq'] for k in indices],accepted_us=[rows[k]['us'] for k in indices],
        current_replacement=False,time_compression=False,voltage_history_discarded=False,
        rs_input_ohm=rs,inductance_h=None,automatic_pi_write=False)
    if len(intervals)<MIN_MODEL_INTERVALS:
        out['quality_error']='Insufficient complete voltage-history intervals';return out
    evidence=run.get('latch_evidence',{})
    verified=(evidence.get('verified') is True and evidence.get('command_lag_cycles')==2 and
        evidence.get('late_count')==0 and bool(evidence.get('source')))
    if fraction is None:
        fraction=evidence.get('sample_to_bottom_fraction')
        if not verified:
            out['quality_error']='TIMING_UNQUALIFIED; samples retained for later proof';return out
    else:
        # Explicit sensitivity calculation never upgrades a capture to verified.
        verified=False;out['diagnostic_static_fraction_assumption']=fraction
    if not isinstance(fraction,(int,float)) or not math.isfinite(fraction) or not 0<fraction<1:
        raise ValueError('Explicit valid fraction required')
    current,voltage=('id','vd') if run['mode']=='LD' else ('iq','vq')
    other='iq' if current=='id' else 'id'
    span=max(rows[k][current] for k in indices)-min(rows[k][current] for k in indices)
    cross=st.mean(rows[k][other] for k in indices)
    out.update(current_span_a=span,mean_cross_axis_a=cross)
    if span<.015 or abs(cross)>.02:
        out['quality_error']='Transient span/cross-axis quality inadequate';return out
    # Same tau search/residual/identifiability gates as original fit_l.
    raw_dt=[b['us']-a['us'] for a,b in zip(rows,rows[1:]) if b['seq']==a['seq']+1]
    lo=3*st.mean(raw_dt)*1e-6;hi=(rows[-1]['us']-rows[0]['us'])*.5e-6
    def evaluate(tau):
        terms=[]
        for left,right,parts in intervals:
            pred=rows[left][current];decay=1.
            for old,new,dt in parts:
                a=math.exp(-dt/tau);b=math.exp(-(1-fraction)*dt/tau)
                pred=a*pred+(b-a)*rows[old][voltage]/rs+(1-b)*rows[new][voltage]/rs
                decay*=a
            terms.append((rows[right][current]-pred,(1-decay)/rs))
        bias=sum(y*x for y,x in terms)/sum(x*x for _,x in terms)
        return st.mean((y-bias*x)**2 for y,x in terms),bias
    grid=[lo*(hi/lo)**(k/319) for k in range(320)]
    errors=[evaluate(t) for t in grid];best=min(range(320),key=lambda k:errors[k][0])
    tau=grid[best];mse,bias=errors[best];rms=math.sqrt(mse);limit=min(.005,.15*span)
    out.update(prediction_rms_a=rms,original_rms_limit_a=limit,
        boundary_minimum=best<3 or best>316,fitted_voltage_bias_v=bias)
    if best<3 or best>316 or rms>limit:
        out['quality_error']='Unresolved tau boundary or noisy/model-inconsistent remaining samples';return out
    if min(evaluate(tau*.75)[0],evaluate(tau*1.25)[0])<max(mse*1.2,1e-10):
        out['quality_error']='Remaining samples do not identify a unique time constant';return out
    if not verified:
        out['quality_error']='NUMERIC_MODEL_ONLY: latch evidence still unverified';return out
    out.update(inductance_h=tau*rs,tau_s=tau)
    return out


@lru_cache(maxsize=4)
def pinned_symbols(elf,expected):
    if hashlib.sha256(elf.read_bytes()).hexdigest()!=expected:raise ValueError('Exact saved ELF required')
    return symbols(elf)


def load_saved(path):
    r=json.loads(path.read_text('utf-8'));capture=r.get('ident_run')
    if not capture:return r,None
    voltage=bool(r.get('voltage_step'))
    preset='MotorParameterIdentificationVoltageStepDiagnostic' if voltage else 'MotorParameterIdentificationLAdmissionDiagnostic'
    elf=ROOT/'foc2_app_a/build'/preset/'foc2.elf'
    sy=pinned_symbols(elf,r['elf_sha256']);ram=Path(r['ram_capture']).read_bytes();flash=Path(r['final_capture']).read_bytes()
    image=elf.with_suffix('.bin').read_bytes()
    if (hashlib.sha256(ram).hexdigest()!=r['ram_sha256'] or len(ram)!=0x20000 or
        hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
        hashlib.sha256(image).hexdigest()!=r['image_sha256'] or flash[0x8000:0x8000+len(image)]!=image):
        raise ValueError('Same-session raw provenance mismatch')
    address,size=sy['motor_ident'];off=address-0x20000000
    if size!=1740:raise ValueError('Exact identification ABI required')
    n=struct.unpack_from('<I',ram,off+1536)[0]
    if n>32:raise ValueError('Invalid capture count')
    keys=('us seq pending_before raw_u raw_v tail_cnt tail_flags id iq vd vq angle speed mode status reason reserved'
        if voltage else 'us seq pending_before id_ref iq_ref id iq vd vq angle speed mode status reason reserved').split()
    actual=[dict(zip(keys,struct.unpack_from('<3I4H6f4B' if voltage else '<3I8f4B',ram,off+k*48))) for k in range(n)]
    if voltage:
        for row in actual:row.update(id_ref=0.,iq_ref=0.)
    if actual!=capture['rows']:raise ValueError('JSON rows differ from binary observations')
    return r,capture


def batch_report(path,rs=.78,fraction=None):
    batch=json.loads(path.read_text('utf-8'));points=[]
    for source in batch['points']:
        r,capture=load_saved(Path(source));entry=dict(receipt=source,axis=r['axis'],repeat=r['repeat'])
        if capture is None:entry['quality_error']='No capture'
        else:
            try:entry.update(fit_observations(capture,rs,fraction))
            except original.Insufficient as e:entry['quality_error']=str(e)
        points.append(entry)
    return dict(offline_only=True,firmware_changed=False,protection_changed=False,original_data_changed=False,
        filter_policy=dict(min_spike_a=MIN_SPIKE_A,mad_multiplier=MAD_MULTIPLIER,
            min_keep_fraction=MIN_KEEP_FRACTION,min_current_samples=MIN_CURRENT_SAMPLES,
            min_model_intervals=MIN_MODEL_INTERVALS),rs_assumption_ohm=rs,
        automatic_pi_write=False,ld=None,lq=None,points=points)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch',type=Path)
    p.add_argument('--rs-ohm',type=float,default=.78)
    p.add_argument('--diagnostic-static-fraction',type=float,help='Sensitivity only; never marks timing verified')
    a=p.parse_args();print(json.dumps(batch_report(a.batch,a.rs_ohm,a.diagnostic_static_fraction),indent=2))


if __name__=='__main__':main()
