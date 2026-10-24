"""Offline search-bound sensitivity; never qualifies or writes motor parameters."""
import argparse
import json
import math
from pathlib import Path
import statistics as st

import motor_ident_valid_sample_report as admission


def search_run(run, rs=.78, fraction=.5005):
    # Retain original admission and quality evidence, including cross-axis checks.
    baseline=admission.fit_observations(run,rs,fraction)
    out=dict(baseline_quality=baseline, diagnostic_only=True, qualified=False,
             rs_ohm=rs, static_fraction_assumption=fraction, searches=[])
    if 'prediction_rms_a' not in baseline:
        out['not_searched']=baseline.get('quality_error');return out
    rows,keep,_=admission.select_samples(run)
    intervals,_=admission.available_intervals(rows,keep)
    current,voltage=('id','vd') if run['mode']=='LD' else ('iq','vq')
    def objective(tau):
        # Same RL prediction/constant voltage-bias nuisance fit as baseline.
        terms=[]
        for left,right,parts in intervals:
            pred=rows[left][current];decay=1.
            for old,new,dt in parts:
                a=math.exp(-dt/tau);b=math.exp(-(1-fraction)*dt/tau)
                pred=a*pred+(b-a)*rows[old][voltage]/rs+(1-b)*rows[new][voltage]/rs
                decay*=a
            terms.append((rows[right][current]-pred,(1-decay)/rs))
        bias=sum(y*x for y,x in terms)/sum(x*x for _,x in terms)
        return math.sqrt(st.mean((y-bias*x)**2 for y,x in terms)),bias
    dt=st.mean(b['us']-a['us'] for a,b in zip(rows,rows[1:]) if b['seq']==a['seq']+1)
    upper=(rows[-1]['us']-rows[0]['us'])*.5
    for lower in (3*dt,100.,50.,20.,10.,5.,1.,.1,.01):
        # Dense log grid then refine only an interior minimum; no sample edits.
        grid=[lower*(upper/lower)**(k/2047) for k in range(2048)]
        scores=[objective(t*1e-6)[0] for t in grid]
        best=min(range(len(grid)),key=scores.__getitem__)
        tau_us=grid[best]
        if 0<best<len(grid)-1:
            left,right=math.log(grid[best-1]),math.log(grid[best+1])
            for _ in range(48):
                x=left+(right-left)/3;y=right-(right-left)/3
                if objective(math.exp(x)*1e-6)[0]<objective(math.exp(y)*1e-6)[0]:right=y
                else:left=x
            tau_us=math.exp((left+right)/2)
        rms,bias=objective(tau_us*1e-6)
        near=[tau_us]+[t for t,e in zip(grid,scores) if e<=rms*1.01+1e-15]
        out['searches'].append(dict(lower_us=lower,upper_us=upper,
            best_tau_us=tau_us,unqualified_best_L_uH=rs*tau_us,
            prediction_rms_mA=rms*1000,voltage_bias_v=bias,
            boundary=('LOWER' if best==0 else 'UPPER' if best==2047 else 'INTERIOR'),
            within_one_percent_rms_tau_range_us=[min(near),max(near)]))
    return out


def batch_search(path,rs=.78,fraction=.5005):
    batch=json.loads(path.read_text('utf-8'));points=[]
    for source in batch['points']:
        meta,run=admission.load_saved(Path(source))
        point=dict(axis=meta['axis'],repeat=meta['repeat'],receipt=source)
        try:
            if run is None:raise admission.original.Insufficient('No capture')
            point.update(search_run(run,rs,fraction))
        except admission.original.Insufficient as e:point['not_searched']=str(e)
        points.append(point)
    return dict(offline_only=True,qualified=False,firmware_changed=False,
                automatic_parameter_write=False,points=points)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch',type=Path)
    parser.add_argument('--rs-ohm',type=float,default=.78)
    parser.add_argument('--diagnostic-static-fraction',type=float,default=.5005)
    args=parser.parse_args()
    print(json.dumps(batch_search(args.batch,args.rs_ohm,args.diagnostic_static_fraction),indent=2))


if __name__=='__main__':main()
