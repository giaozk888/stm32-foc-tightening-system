"""FILES ONLY: positive-speed three-term mechanical fit, no device writes.

For positive motion only, Tc/Kt and current bias are inseparable. Fit their
SUM explicitly; never invent a negative-direction observation or calibrated Kt.
Original fixed window admission is reused without residual-based selection.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import mechanical_identification_report as original


def solve(points):
    if len(points)<3:raise ValueError('INSUFFICIENT_WINDOWS')
    if any(p['direction']!=1 for p in points):raise ValueError('POSITIVE_ONLY_REQUIRED')
    x=[[p['alpha'],p['omega'],1.] for p in points]
    weights=[p['dt_s'] for p in points];sw=sum(weights)
    scale=[math.sqrt(sum(w*v[j]**2 for w,v in zip(weights,x))/sw) for j in range(3)]
    if any(s<1e-12 for s in scale):raise ValueError('RANK_DEFICIENT')
    z=[[v[j]/scale[j] for j in range(3)] for v in x]
    gram=[[sum(w*v[j]*v[k] for w,v in zip(weights,z))/sw for k in range(3)] for j in range(3)]
    rhs=[sum(w*v[j]*p['iq'] for w,v,p in zip(weights,z,points))/sw for j in range(3)]
    a=[gram[j][:]+[float(j==k) for k in range(3)]+[rhs[j]] for j in range(3)]
    for col in range(3):
        pivot=max(range(col,3),key=lambda i:abs(a[i][col]))
        if abs(a[pivot][col])<1e-9:raise ValueError('RANK_DEFICIENT')
        a[col],a[pivot]=a[pivot],a[col];d=a[col][col];a[col]=[v/d for v in a[col]]
        for row in range(3):
            if row!=col:
                q=a[row][col];a[row]=[v-q*u for v,u in zip(a[row],a[col])]
    coef=[a[j][6]/scale[j] for j in range(3)]
    errors=[p['iq']-sum(c*v for c,v in zip(coef,row)) for row,p in zip(x,points)]
    mean=sum(w*p['iq'] for w,p in zip(weights,points))/sw
    sse=sum(w*e*e for w,e in zip(weights,errors));sst=sum(w*(p['iq']-mean)**2 for w,p in zip(weights,points))
    cond=max(sum(abs(v) for v in row) for row in gram)*max(sum(abs(v) for v in row[3:6]) for row in a)
    return dict(j_over_kt=coef[0],b_over_kt=coef[1],positive_friction_plus_bias_a=coef[2],
        r2=1-sse/sst if sst>1e-20 else 0,residual_rms_a=math.sqrt(sse/sw),condition_inf_scaled=cond)


def fit(rows,group=1):
    accepted,rejected=original.windows(rows,group)
    result=dict(n=len(accepted),rejected_n=len(rejected),group=group,problems=[],qualified=False)
    if len(accepted)<40:result['problems'].append('INSUFFICIENT_WINDOWS');return result
    if statistics.pstdev(p['alpha'] for p in accepted)<5:result['problems'].append('INSUFFICIENT_ACCELERATION_EXCITATION')
    if statistics.pstdev(p['omega'] for p in accepted)<2:result['problems'].append('INSUFFICIENT_SPEED_EXCITATION')
    try:result.update(solve(accepted))
    except ValueError as error:result['problems'].append(str(error));return result
    if result['j_over_kt']<=0 or result['b_over_kt']<0:result['problems'].append('NONPHYSICAL_COEFFICIENT')
    if result['condition_inf_scaled']>1e5:result['problems'].append('ILL_CONDITIONED')
    if result['r2']<.7 or result['residual_rms_a']>.03:result['problems'].append('POOR_MODEL_FIT')
    result['qualified']=not result['problems'];return result


def report(captures):
    rows=[r for c in captures for r in c['rows']]
    primary=fit(rows);double=fit(rows,2);issues=list(primary['problems'])
    if not captures or not all(c.get('board_verified') for c in captures):issues.append('BOARD_ACCEPTANCE_NOT_VERIFIED')
    change=None
    if not double['qualified']:issues.append('DOUBLE_WINDOW_FIT_FAILED')
    elif primary.get('j_over_kt',0)>0:
        change=100*(double['j_over_kt']/primary['j_over_kt']-1)
        if abs(change)>30:issues.append('WINDOW_SENSITIVE')
    sessions=list(dict.fromkeys(r['session'] for r in rows));heldout=[]
    if len(sessions)<3:issues.append('INDEPENDENT_SESSIONS_REQUIRED')
    else:
        accepted,_=original.windows(rows,1)
        for session in sessions:
            train=fit([r for r in rows if r['session']!=session])
            test=[p for p in accepted if p['session']==session]
            rms=None;valid=bool(train['qualified'] and test)
            if valid:
                errors=[p['iq']-(train['j_over_kt']*p['alpha']+train['b_over_kt']*p['omega']+
                    train['positive_friction_plus_bias_a']) for p in test]
                rms=math.sqrt(sum(e*e for e in errors)/len(errors))
                valid=bool(rms<=.03 and primary.get('j_over_kt',0)>0 and
                    abs(train['j_over_kt']/primary['j_over_kt']-1)<=.3)
            heldout.append(dict(session=session,passed=valid,residual_rms_a=rms))
        if not all(p['passed'] for p in heldout):issues.append('SESSION_SENSITIVITY')
    return dict(primary=primary,sensitivity=double,window_change_percent=change,heldout=heldout,
        problems=sorted(set(issues)),normalized_positive_qualified=not issues,
        formula='Iq_lp20 = J/Kt * actual_alpha + B/Kt * omega + (Tc/Kt + bias)',
        scope='Positive motion only. Coulomb friction and current bias remain inseparable.',
        kt_independently_identified=False,absolute_parameters=None,parameter_writes=False,dob_control_enabled=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts',type=Path,nargs='+',required=True)
    parser.add_argument('--elf',type=Path,required=True)
    args=parser.parse_args(argv)
    if len({p.resolve() for p in args.receipts})!=len(args.receipts):parser.error('Duplicate receipts')
    captures=[original.decode(p,args.elf) for p in args.receipts]
    if len({c['session_hash'] for c in captures})!=len(captures):parser.error('Duplicate captures')
    print(json.dumps(report(captures),indent=2,allow_nan=False))


if __name__=='__main__':main()
