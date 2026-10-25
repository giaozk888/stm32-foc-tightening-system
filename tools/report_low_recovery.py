"""Independent estimator-only Simulink audit. Never treats DOB as load truth."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stat(v):
    x=[a for a in v if a is not None and math.isfinite(a)]
    return dict(n=len(x),mean=statistics.mean(x) if x else None,sd=statistics.stdev(x) if len(x)>1 else None)
def read(p):
    with gzip.open(p,'rt',newline='') as f:return [{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]
def trial(rows,run,profile):
    p=profile+'_';haslow=run['scenario']!='no_low';begin=run['return_start_s']
    search=[r for r in rows if begin<=r['time_s']<begin+1.]
    live=[r for r in search if r[p+'valid'] and r['protection_fault']==0]
    first=live[0]['time_s'] if live else None
    exit_epoch=next((r['time_s'] for r in rows if r['time_s']>=begin and abs(r['omega_meas_rad_s'])>=1.0471975511965977),None)
    window=[r for r in rows if begin<=r['time_s']<begin+.5 and not r['protection_fault']]
    valid=[r for r in window if r[p+'valid']]
    errors=[r[p+'estimate_a']-r['load_truth_a'] for r in valid]
    comp_errors=[abs(r[p+'shadow_comp_a']-max(-.025,min(.025,.25*r['load_truth_a']))) for r in window]
    allvalid=[r for r in rows if r['time_s']>=1 and r['time_s']<6.9 and r[p+'valid']]
    return dict(scenario=run['scenario'],seed=run['seed'],split='train' if run['seed']<=5 else 'heldout',profile=profile,
        recovery_ms=(first-exit_epoch)*1000 if haslow and first is not None and exit_epoch is not None else None,
        recovery_from_platform_ms=(first-begin)*1000 if haslow and first is not None else None,
        valid_rmse_a=math.sqrt(stat([e*e for e in errors])['mean']) if errors else None,
        valid_bias_a=stat(errors)['mean'],valid_peak_error_a=max(map(abs,errors),default=None),
        recovery_valid_rate=len(valid)/len(window) if window else None,
        shadow_comp_error_peak_a=max(comp_errors,default=None),
        all_valid_rmse_a=math.sqrt(stat([(r[p+'estimate_a']-r['load_truth_a'])**2 for r in allvalid])['mean']) if allvalid else None,
        fast=rows[-1][p+'fast'],fallback=rows[-1][p+'cold'],raw_reset_calls=rows[-1][p+'raw_reset_calls'],
        shadow_peak_a=max(abs(r[p+'shadow_comp_a']) for r in rows),
        no_valid_during_low=all(not r[p+'valid'] for r in rows if abs(r['omega_meas_rad_s'])<1.0471974),
        no_valid_after_fault=all(not r[p+'valid'] and r[p+'shadow_comp_a']==0 for r in rows if r['protection_fault']))

def audit(root,reference=None):
    m=json.loads((root/'manifest.json').read_text());done=json.loads((root/'report.json').read_text())
    assert done['completed'] and done['consumed_input_verified'] and not done['feedback_applied_to_plant']
    profiles=m.get('profiles',['baseline','retain']);metrics=[];records=[]
    for s in m['sources']:
        path=Path(s['path'])
        if sha(path)!=s['sha256']:
            path=root/'frozen_sources'/path.name
        assert path.exists() and sha(path)==s['sha256'],'Source pin changed: '+s['path']
    for run in m['runs']:
        file=root/f"{run['scenario']}_seed{run['seed']:03d}.csv.gz";rows=read(file)
        assert len(rows)==run['rows']==7001 and sha(run['input'])==run['sha256']
        original=list(struct.iter_unpack('<16d',Path(run['input']).read_bytes()))
        for i,r in enumerate(rows):
            assert all(math.isfinite(x) for x in r.values())
            assert all(math.isclose(r[k],v,rel_tol=5e-14,abs_tol=1e-12) for k,v in zip(m['input_names'],original[i]))
            for profile in profiles:
                p=profile+'_';assert r[p+'valid'] in (0,1) and abs(r[p+'shadow_comp_a'])<=.025001
                if i and r[p+'feedback_state']==2:
                    assert abs(r[p+'shadow_comp_a']-rows[i-1][p+'shadow_comp_a'])<=.0002501
                if run['scenario']=='spike' and r['id_meas_a']>.6:
                    assert r[p+'filter_updated']==0 and r[p+'abs_id_lpf']==rows[i-1][p+'abs_id_lpf']
        if reference:
            older=read(reference/file.name);assert len(older)==len(rows)
            for r,old in zip(rows,older):
                assert all(r[k]==v for k,v in old.items()),'Baseline/150ms reference drift'
        for profile in profiles:metrics.append(trial(rows,run,profile))
        records.append(dict(path=str(file),sha256=sha(file),rows=len(rows)))
    with (root/'metrics_per_trial.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=metrics[0]);writer.writeheader();writer.writerows(metrics)
    scenarios=sorted({r['scenario'] for r in metrics});summaries=[];checks={}
    for s in scenarios:
        for profile in profiles:
            group=[r for r in metrics if r['scenario']==s and r['profile']==profile];assert len(group)==10
            keys=['recovery_ms','recovery_from_platform_ms','valid_rmse_a','valid_bias_a','valid_peak_error_a','recovery_valid_rate',
                'shadow_comp_error_peak_a','all_valid_rmse_a','raw_reset_calls','shadow_peak_a']
            summaries.append(dict(scenario=s,profile=profile,fast=sum(r['fast'] for r in group),
                fallback=sum(r['fallback'] for r in group),**{k:stat([r[k] for r in group]) for k in keys}))
    for profile in profiles[1:]:
        pp={}
        for r in [x for x in metrics if x['profile']==profile]:
            b=next(x for x in metrics if x['profile']=='baseline' and x['scenario']==r['scenario'] and x['seed']==r['seed'])
            prefix=r['scenario']+'_'+str(r['seed'])
            pp[prefix+'_low_invalid']=r['no_valid_during_low']
            pp[prefix+'_fault_invalid']=r['no_valid_after_fault']
            if r['recovery_ms'] is not None and b['recovery_ms'] is not None:
                pp[prefix+'_not_slower']=r['recovery_ms']<=b['recovery_ms']+1.01
            if r['valid_rmse_a'] is not None:
                pp[prefix+'_rmse']=r['valid_rmse_a']<=m['acceptance']['max_valid_rmse_a']
                pp[prefix+'_bias']=abs(r['valid_bias_a'])<=m['acceptance']['max_valid_bias_a']
            if r['shadow_comp_error_peak_a'] is not None and b['shadow_comp_error_peak_a'] is not None:
                pp[prefix+'_extra_shadow_comp']=r['shadow_comp_error_peak_a']<=b['shadow_comp_error_peak_a']+m['acceptance']['max_extra_shadow_comp_a']
            if r['scenario'] in ('long150','reverse','spike','source_gap','persistent_id','fault'):
                pp[prefix+'_unsafe_no_fast']=r['fast']==0
        clean=[r for r in metrics if r['profile']==profile and r['scenario'] in ('short20','short60','short90')]
        useful=all(stat([r['recovery_ms'] for r in clean if r['scenario']==s])['mean'] <
            stat([r['recovery_ms'] for r in metrics if r['profile']=='baseline' and r['scenario']==s])['mean']-1
            for s in ('short20','short60','short90')) and sum(r['fast'] for r in clean)>0
        checks[profile]=dict(passed=all(pp.values()),safety_accuracy_passed=all(pp.values()),
            improves_clean_short_cases=useful,failed=[k for k,v in pp.items() if not v],checks=pp)
    result=dict(audit='PASS',profiles=profiles,repeats=10,scenarios=len(scenarios),runs=done['runs'],
        summaries=summaries,acceptance=checks,logs=records,
        reference_replayed_identically=reference is not None,physical_performance_validated=False,
        feedback_applied_to_plant=False,
        scope='Estimator first: error window first500ms after prescribed low-speed platform. Recovery latency from first measured speed>=10rpm after platform; platform-origin latency retained separately. Valid-only error and coverage reported together. Same exogenous inputs, independent load. No speed-performance or closed-loop superiority claim.')
    (root/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    flat=[]
    for r in summaries:
        row={}
        for k,v in r.items():
            if isinstance(v,dict):row.update({k+'_'+z:n for z,n in v.items()})
            else:row[k]=v
        flat.append(row)
    with (root/'metrics_mean_std.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=flat[0]);w.writeheader();w.writerows(flat)
    print(json.dumps(dict(audit='PASS',acceptance={p:dict(passed=v['passed'],failed=v['failed']) for p,v in checks.items()}),indent=2))
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('--reference',type=Path)
    a=p.parse_args();audit(a.root,a.reference)
