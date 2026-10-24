"""File-only steady dq COMMAND-voltage model estimates, never device access.

Rs/Ld are the CURRENT A assumptions, NOT inferred from PI or overwritten.
The resulting flux is an effective candidate, not open-circuit metrology.
"""
import argparse
import json
import math
import re
from pathlib import Path
import statistics

POINTS=(100,200,300,400)
RS_OHM=.78
LD_H=20.03e-6
POLE_PAIRS=10


def trace_coverage(rows,last_index,window_samples):
    """Join ONLY identical observation indices; never nearby UART times."""
    joined={}
    for entry in rows:
        line=entry.get('decoded','')
        if '\u25a0msg\u2666' in line:line=line.split('\u25a0msg\u2666',1)[1].split('\u25a0',1)[0]
        m=re.search(r'\bPSI ([RIES]) ',line)
        if not m:continue
        fields=dict(re.findall(r'([A-Za-z0-9_]+)=([^\s]+)',line))
        if 'index' not in fields:continue
        index=int(fields['index']);parts=joined.setdefault(index,{})
        if m[1] in parts and parts[m[1]]!=fields:raise ValueError('Conflicting PSI observation index')
        parts[m[1]]=fields
    needed=list(range(max(1,last_index-window_samples+1),last_index+1)) if window_samples else []
    missing=[i for i in needed if set(joined.get(i,{}))!=set('RIES')]
    return dict(expected_window_frames=len(needed),complete_window_frames=len(needed)-len(missing),
        missing_or_partial_indices=missing,complete=bool(needed) and not missing,
        summary_source='RAM aggregates; UART coverage reported separately, never zero-filled')


def plan(api_limit=250,overspeed=300,points=POINTS):
    if not points or len(set(points))!=len(points) or any(r not in POINTS for r in points):
        raise ValueError('Explicit unique supported speed points required')
    return dict(requested=list(points),
        runnable=[r for r in points if r<=api_limit and r<overspeed],
        skipped=[dict(rpm=r,reason='EXISTING_SPEED_LIMIT') for r in points if r>api_limit or r>=overspeed],
        api_limit_rpm=api_limit,overspeed_trip_rpm=overspeed,
        rs_ohm=RS_OHM,ld_h=LD_H,pole_pairs=POLE_PAIRS,min_valid_rpm=50,
        stable_ms=500,window_ms=2000,drive_max_ms=5000,point_max_ms=7000,
        lease_us=12000000,one_batch=True,one_point_per_protected_boot=True,
        repeats=1,auto_retry=False,auto_apply=False)


def point(s,rs=RS_OHM,ld=LD_H,pairs=POLE_PAIRS):
    m=s['mean']
    if len(m)!=8 or not all(math.isfinite(x) for x in m):raise ValueError('Invalid means')
    passed=bool(s['passed'] and s['finished'] and not s['active'] and s['window_complete'] and
                s['valid']>=38 and s['seen'] and s['reject']<=.05*s['seen'] and s['stage']==2)
    return dict(target_rpm=s['rpm'],passed=passed,rs_ohm=rs,ld_h=ld,pole_pairs=pairs,
        valid=s['valid'],reject=s['reject'],seen=s['seen'],stage=s['stage'],
        mean_rpm=m[0],mean_id_a=m[1],mean_iq_a=m[2],mean_vq_v=m[3],
        mean_bemf_v=m[4],mean_psi_wb=m[5],mean_we_rad_s=m[6],mean_vd_v=m[7],
        psi_sd_wb=math.sqrt(max(0,s['psi_m2']/(s['valid']-1))) if s['valid']>1 else None)


def fit(points):
    valid=[p for p in points if p.get('passed')]
    result=dict(candidate=None,points=points,valid_points=len(valid),
        automatic_parameter_write=False,automatic_feedforward_apply=False,
        qualified_physical_flux=False,voltage_source='PWM command, NOT measured phase terminal voltage',
        warning='Steady-state model neglects dIq/dt. Existing Rs/Ld are unqualified assumptions; dead time, bus calibration and voltage errors can bias flux. No automatic activation.')
    if any(p.get('fault') for p in points):
        result['reason']='PROTECTION_ABORT';return result
    if len(valid)<2 or len({p['target_rpm'] for p in valid})<2:
        result['reason']='NEED_TWO_DISTINCT_VALID_SPEED_POINTS';return result
    models={(p['rs_ohm'],p['ld_h'],p['pole_pairs']) for p in valid}
    if len(models)!=1:raise ValueError('Cannot mix Rs/Ld/pole-pair assumptions')
    x=[p['mean_we_rad_s'] for p in valid];y=[p['mean_bemf_v'] for p in valid]
    if not all(math.isfinite(v) for v in x+y):raise ValueError('Nonfinite fit')
    xm,ym=statistics.mean(x),statistics.mean(y)
    sxx=sum((v-xm)**2 for v in x)
    if sxx<=1e-12:raise ValueError('Degenerate speed span')
    psi=sum((a-xm)*(b-ym) for a,b in zip(x,y))/sxx;offset=ym-psi*xm
    residuals=[b-(psi*a+offset) for a,b in zip(x,y)]
    sse=sum(r*r for r in residuals);syy=sum((b-ym)**2 for b in y)
    pairs=valid[0]['pole_pairs']
    result['candidate']=dict(psi_f_wb=psi,offset_v=offset,r_squared=1-sse/syy if syy>1e-20 else None,
        residual_rms_v=math.sqrt(sse/len(x)),residual_dof=len(x)-2,
        ke_phase_peak_v_per_mech_rad_s=pairs*psi,
        ke_definition='phase-to-neutral PEAK V per mechanical rad/s; Ke=pole_pairs*psi_f',
        positive_flux=psi>0,parameters_origin=dict(rs_ohm=valid[0]['rs_ohm'],ld_h=valid[0]['ld_h'],pole_pairs=pairs))
    if len(x)==2:result['fit_warning']='TWO_POINTS_ZERO_RESIDUAL_DOF: R2=1 is algebraic, not independent validation'
    if psi<=0:result['fit_warning']='NONPOSITIVE_FLUX: retain estimate, do NOT activate compensation'
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',type=Path)
    p.add_argument('--output',type=Path);a=p.parse_args()
    if a.batch:
        batch=json.loads(a.batch.read_text());points=batch.get('results',[])
        result=fit(points)
        if batch.get('failure'):
            result['candidate']=None;result['reason']='BATCH_ABORTED';result['failure']=batch['failure']
    else:result=plan()
    text=json.dumps(result,indent=2,allow_nan=False)
    if a.output:a.output.write_text(text+'\n',encoding='utf-8')
    print(text);return 0


if __name__=='__main__':raise SystemExit(main())
