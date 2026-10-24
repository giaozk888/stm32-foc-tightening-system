"""FILES ONLY: fit measured Iq-friction against measured acceleration, never accel_ref.

No serial, programmer, device access or automatic parameter writes. Published
100ms windows contain trapezoidal current averages and measured-speed endpoints.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

FIELDS=('seq start_us end_us flags speed_start_rpm speed_end_rpm mean_iq_a '
        'mean_friction_a mean_speed_ref_rpm mean_speed_meas_rpm').split()
MIN_SPEED_RPM=10.0
MIN_WINDOWS=8
MIN_ACCEL_STD_RPM_S=20.0
MIN_R2=0.6
MAX_RESIDUAL_SPEED_CORRELATION=0.5
MAX_EXISTING_KA=0.00025
MULTIPLIERS=(0.5,0.75,1.0,1.25)


def decode(receipt,elf):
    from foc_path_profile_report import symbols
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes()
    flash=Path(r['final_capture']).read_bytes();image=elf.with_suffix('.bin').read_bytes()
    if (len(ram)!=0x20000 or hashlib.sha256(ram).hexdigest()!=r['ram_sha256'] or
        hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
        hashlib.sha256(elf.read_bytes()).hexdigest()!=r['elf_sha256'] or
        hashlib.sha256(image).hexdigest()!=r['image_sha256'] or
        flash[0x8000:0x8000+len(image)]!=image):
        raise ValueError('Same-session exact A BIN/ELF/Flash/RAM required')
    addr,size=symbols(elf)['ka_identification'];offset=addr-0x20000000
    if size!=1032 or not 0<=offset<=len(ram)-size:raise ValueError('Ka ABI mismatch')
    generation,count,samples=struct.unpack_from('<3I',ram,offset+960)
    if count>24:raise ValueError('Invalid publication count')
    result=r.get('result',{})
    return dict(source='hardware_receipt',receipt=str(receipt),generation=generation,samples=samples,
        # A process timeout in an empty-load recipe is NOT necessarily a motor fault.
        # Hardware acceptance still belongs to the existing board classifier.
        closure_verified=bool(r.get('final_cpu_halted') and r.get('final_outputs_off') and
                              r.get('all_app_private_unchanged')),
        board_acceptance_verified=bool(r.get('preflight_pass') and result.get('acquisition_complete') and
            result.get('deadline_miss')==0 and result.get('ccr_late')==0 and
            result.get('full_uart_telemetry_complete') and result.get('expected_process_timeout_snapshot')),
        windows=[dict(zip(FIELDS,struct.unpack_from('<4I6f',ram,offset+i*40))) for i in range(count)])


def correlation(x,y,weights):
    weight=sum(weights);mx=sum(a*w for a,w in zip(x,weights))/weight
    my=sum(a*w for a,w in zip(y,weights))/weight
    xx=sum(w*(a-mx)**2 for a,w in zip(x,weights));yy=sum(w*(a-my)**2 for a,w in zip(y,weights))
    return sum(w*(a-mx)*(b-my) for a,b,w in zip(x,y,weights))/math.sqrt(xx*yy) if xx*yy>1e-24 else 0.0


def fit_direction(windows,direction,duration_bounds=(0.09,0.105)):
    accepted=[];rejected=[]
    for f in windows:
        reasons=[]
        if not all(isinstance(f.get(k),(int,float)) and math.isfinite(f[k]) for k in FIELDS):
            rejected.append(dict(seq=f.get('seq'),reasons=['MISSING_OR_NONFINITE']));continue
        duration=((int(f['end_us'])-int(f['start_us']))&0xffffffff)*1e-6
        if f['flags']:reasons.append('OBSERVATION_QUALITY_FLAGS')
        if not duration_bounds[0]<=duration<=duration_bounds[1]:reasons.append('WINDOW_DURATION')
        if min(direction*f['speed_start_rpm'],direction*f['speed_end_rpm'])<MIN_SPEED_RPM:
            reasons.append('REST_STICTION_OR_OTHER_DIRECTION')
        if reasons:
            rejected.append(dict(seq=f['seq'],reasons=reasons));continue
        acceleration=(f['speed_end_rpm']-f['speed_start_rpm'])/duration
        accepted.append(dict(seq=f['seq'],acceleration_rpm_s=acceleration,
            iq_minus_friction_a=f['mean_iq_a']-f['mean_friction_a'],duration_s=duration,
            speed_meas_rpm=f['mean_speed_meas_rpm']))
    out=dict(direction=direction,accepted=accepted,rejected=rejected,n=len(accepted),
        trusted=False,ka_identified=None,b_a=None,problems=[])
    if len(accepted)<MIN_WINDOWS:
        out['problems'].append('INSUFFICIENT_WINDOWS');return out
    x=[f['acceleration_rpm_s'] for f in accepted];y=[f['iq_minus_friction_a'] for f in accepted]
    weights=[f['duration_s'] for f in accepted];weight=sum(weights)
    mx=sum(a*w for a,w in zip(x,weights))/weight;my=sum(a*w for a,w in zip(y,weights))/weight
    sxx=sum(w*(a-mx)**2 for a,w in zip(x,weights))
    std=math.sqrt(sxx/weight);out['acceleration_std_rpm_s']=std
    if std<MIN_ACCEL_STD_RPM_S:
        out['problems'].append('INSUFFICIENT_ACCELERATION_EXCITATION');return out
    ka=sum(w*(a-mx)*(b-my) for a,b,w in zip(x,y,weights))/sxx;b=my-ka*mx
    residual=[v-(ka*a+b) for a,v in zip(x,y)]
    sse=sum(w*r*r for w,r in zip(weights,residual));syy=sum(w*(v-my)**2 for w,v in zip(weights,y))
    r2=1-sse/syy if syy>1e-24 else 0.0
    speed_corr=correlation([f['speed_meas_rpm'] for f in accepted],residual,weights)
    leverage=[w/weight+w*(a-mx)**2/sxx for a,w in zip(x,weights)]
    max_leverage=max(leverage)
    loo=[]
    for i in range(len(x)):
        wx=[(a,v,w) for j,(a,v,w) in enumerate(zip(x,y,weights)) if j!=i]
        wt=sum(w for _,_,w in wx)
        ax=sum(a*w for a,_,w in wx)/wt;ay=sum(v*w for _,v,w in wx)/wt
        xx=sum(w*(a-ax)**2 for a,_,w in wx)
        if xx>1e-20:loo.append(sum(w*(a-ax)*(v-ay) for a,v,w in wx)/xx)
    out.update(ka_identified=ka,b_a=b,r2=r2,residual_rms_a=math.sqrt(sse/weight),
        residual_speed_correlation=speed_corr,
        max_window_leverage=max_leverage,dominant_window_seq=accepted[leverage.index(max_leverage)]['seq'],
        leave_one_out_ka_min=min(loo) if loo else None,leave_one_out_ka_max=max(loo) if loo else None,
        nominal_slope_standard_error=math.sqrt(sse/(len(x)-2)/sxx),
        uncertainty_note='Nominal regression error only; correlated filtered speed/current and closed-loop noise can bias the slope. Repeat across runs and compare window lengths.')
    if ka<=0:out['problems'].append('NONPOSITIVE_PHYSICAL_SLOPE')
    if r2<MIN_R2:out['problems'].append('POOR_LINEAR_FIT')
    if abs(speed_corr)>MAX_RESIDUAL_SPEED_CORRELATION:out['problems'].append('RESIDUAL_DEPENDS_ON_SPEED')
    if max_leverage>0.5:out['problems'].append('SINGLE_WINDOW_DOMINATES_FIT')
    if ka>0 and loo and (min(loo)<=0 or max(abs(v/ka-1) for v in loo)>0.5):
        out['problems'].append('LEAVE_ONE_OUT_SLOPE_UNSTABLE')
    out['trusted']=not out['problems']
    out['candidates']=[dict(multiplier=m,ka_a_per_rpm_s=ka*m,
        ff_peak_a_at_200_rpm_s=abs(ka*m)*200,
        within_existing_ka_cap=0<=ka*m<=MAX_EXISTING_KA,
        enabled_for_manual_review=out['trusted'] and 0<=ka*m<=MAX_EXISTING_KA) for m in MULTIPLIERS]
    return out


def coarsen(windows):
    """Nonoverlapping 200ms sensitivity check; no residual-selected windows."""
    result=[]
    for i in range(0,len(windows)-1,2):
        a,b=windows[i:i+2]
        if a['end_us']!=b['start_us']:raise ValueError('Non-contiguous windows')
        da=(a['end_us']-a['start_us'])&0xffffffff;db=(b['end_us']-b['start_us'])&0xffffffff
        if da+db==0:raise ValueError('Zero-duration windows')
        f=dict(a,seq=len(result)+1,end_us=b['end_us'],flags=a['flags']|b['flags'],speed_end_rpm=b['speed_end_rpm'])
        for k in ('mean_iq_a','mean_friction_a','mean_speed_ref_rpm','mean_speed_meas_rpm'):
            f[k]=(a[k]*da+b[k]*db)/(da+db)
        result.append(f)
    return result


def report(data):
    windows=data['windows']
    # Reject duplicate/missing sequences rather than silently pooling boots/runs.
    if any(f.get('seq')!=i for i,f in enumerate(windows,1)):
        raise ValueError('One run, complete ordered window publication required; do not pool boots')
    directions=[fit_direction(windows,d) for d in (1,-1)]
    coarse=coarsen(windows)
    sensitivity=[fit_direction(coarse,d,(0.18,0.21)) for d in (1,-1)]
    for fine,rough in zip(directions,sensitivity):
        a=fine.get('ka_identified');b=rough.get('ka_identified')
        fine['window_sensitivity_relative']=abs(b/a-1) if a and b else None
        if a and b and abs(b/a-1)>0.3:
            fine['problems'].append('WINDOW_SENSITIVE_SLOPE');fine['trusted']=False
        if data.get('source')=='hardware_receipt' and not (data.get('closure_verified') and data.get('board_acceptance_verified')):
            fine['problems'].append('BOARD_ACCEPTANCE_NOT_VERIFIED');fine['trusted']=False
        for c in fine.get('candidates',[]):
            c['enabled_for_manual_review']=fine['trusted'] and c['within_existing_ka_cap']
    return dict(offline_only=True,hardware_access=False,parameter_writes=False,
        formula='mean(Iq_measured)-mean(Iq_friction_command)=Ka*delta(speed_measured_rpm)/delta(t_s)+b',
        ka_units='A/(rpm/s)',acceleration_source='measured speed endpoints, NOT accel_ref',
        current_source='measured Iq, NOT IqRef',friction_is_physical_measurement=False,
        qualification='b includes residual friction/load and measurement bias. Positive and negative directions are fitted separately. No residual-based sample cherry-picking. All results remain candidate-only.',
        source=data.get('source','exported_windows'),closure_verified=data.get('closure_verified'),
        directions=directions,window_200ms_sensitivity=sensitivity,
        final_ab_objective='time-weighted |speed_ref-speed_meas| throughout the commanded acceleration phase; never gated by t_stable',
        manual_ab_multipliers=list(MULTIPLIERS))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',type=Path)
    p.add_argument('--elf',type=Path);p.add_argument('--windows-json',type=Path);a=p.parse_args(argv)
    if a.windows_json and not a.receipt and not a.elf:data=json.loads(a.windows_json.read_text())
    elif a.receipt and a.elf and not a.windows_json:data=decode(a.receipt,a.elf)
    else:p.error('Use --receipt R --elf E, or --windows-json exported-windows.json; files only')
    print(json.dumps(report(data),indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
