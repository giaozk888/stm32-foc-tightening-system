"""Files-only factorial optimisation audit. Keep original performance screens."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import report_load_gain as base


def analyse(f,scene,variant,profiles):
    mode='adaptive' if variant in profiles else variant
    metrics,checks=base.analyse(f,scene,mode)
    if variant in profiles:
        p=profiles[variant];t=f.time_s.to_numpy();g=f.gain_selected.to_numpy()
        active=(f.control_mode.to_numpy()==3)&(f.fsm_state.to_numpy()==3)
        pair=active[1:]&active[:-1]
        slew=np.diff(g)/np.diff(t)
        checks['gain_slew']=bool((slew[pair]<=p['rise']+.0001).all()&(slew[pair]>=-2.5001).all())
        light=(f.gain_active==0)&(f.gain_quality_valid!=0)&active
        checks['qualified_unloaded_request_equals_floor']=bool(np.allclose(f.gain_requested[light],p['floor'],atol=1e-7,rtol=0))
        invalid=f.gain_quality_valid==0
        # Unknown quality may retain the previous request only for the original short gap.
        bad=f.gain_reason.isin([8,9])&invalid
        checks['no_floor_on_long_invalid']=bool((f.gain_requested[bad]==0).all())
    if scene in ('step','unload','noise','replay','negative_load'):
        floor=profiles.get(variant,dict(floor=0))['floor']
        for name,mask in (('high_gain_request_delay_ms',f.gain_requested>floor+1e-6),('full_gain_delay_ms',f.gain_selected>=.249999)):
            hits=f[(f.time_s>=3)&mask]
            metrics[name]=(float(hits.time_s.iloc[0])-3)*1000 if len(hits) else None
    return metrics,checks


def screen(a,b,scene):
    values=[]
    def add(name,passed):values.append(dict(criterion=name,passed=bool(passed)))
    if scene in ('step','ramp','unload','noise','replay','negative_load'):
        add('loaded_mae_not_worse_5percent_plus_0.1rpm',a.loaded_mae.mean()<=b.loaded_mae.mean()*1.05+.1)
    if scene=='no_load':add('no_load_comp_not_worse_0.1mA',a.compensation_abs_mean_a.mean()<=b.compensation_abs_mean_a.mean()+.0001)
    if scene=='unload':
        add('unload_peak_not_worse_1rpm',a.unload_peak_rpm.mean()<=b.unload_peak_rpm.mean()+1)
        add('unload_recovery_not_worse_50ms',a.unload_recovery_ms.notna().all() and a.unload_recovery_ms.mean()<=b.unload_recovery_ms.mean()+50)
    if scene in ('contact_early','contact_late'):add('no_paired_completion_loss',(~b.done|a.done).all())
    return values


def report(root):
    root=Path(root);m=json.loads((root/'manifest.json').read_text());c=json.loads((root/'config.json').read_text())
    scenes=c['scenarios'] if isinstance(c['scenarios'],list) else [c['scenarios']]
    seeds=c['seeds'] if isinstance(c['seeds'],list) else [c['seeds']]
    pins={f['path']:hashlib.sha256(Path(f['path']).read_bytes()).hexdigest()==f['sha256'] for f in m['sources']+m['firmware_unchanged_pins']}
    pins['opt_dll']=hashlib.sha256(Path(m['dll']).read_bytes()).hexdigest()==m['dll_sha256']
    pins['reference_manifest']=hashlib.sha256((Path(m['baseline_results'])/'manifest.json').read_bytes()).hexdigest()==m['baseline_manifest_sha256']
    refs=json.loads((root/'reference_hashes.json').read_text())
    refs_ok=all(hashlib.sha256((root/r['name']).read_bytes()).hexdigest()==r['sha256']==hashlib.sha256(Path(r['source']).read_bytes()).hexdigest() for r in refs)
    records=[];failures=[];pairs=[]
    profiles=m['profiles'];new=c['new_variants']
    for scene in scenes:
        for seed in seeds:
            frames={}
            for variant in c['variants']:
                f=pd.read_csv(root/f'{scene}_seed{seed:03}_{variant}.csv.gz');frames[variant]=f
                metric,checks=analyse(f,scene,variant,profiles)
                records.append(dict(scene=scene,seed=seed,variant=variant,**metric))
                failures.extend(dict(scene=scene,seed=seed,variant=variant,check=k) for k,v in checks.items() if not v)
            keys=[k for k in frames['off'] if k.startswith('input_') and k not in ('input_omega_true_rad_s','input_iq_true_a','input_position_deg')]
            keys+=['external_load_a','fixture_angle_deg','fixture_enabled','consumed_j_over_kt','consumed_b_over_kt','consumed_ic_over_kt','consumed_bias_a','consumed_current_tau_s']
            ok=all(np.array_equal(frames['off'][keys].to_numpy(),frames[v][keys].to_numpy()) for v in c['variants'][1:])
            pairs.append(dict(scene=scene,seed=seed,identical_actual_conditions=ok))
            print('OPT AUDITED',scene,seed,flush=True)
    R=pd.DataFrame(records);R.to_csv(root/'metrics_per_trial.csv',index=False)
    cols=[k for k in R if k not in ('scene','seed','variant')]
    S=R.groupby(['scene','variant'])[cols].agg(['mean','std','count']);S.columns=['_'.join(k) for k in S.columns]
    S.reset_index().to_csv(root/'metrics_mean_std.csv',index=False);pd.DataFrame(pairs).to_csv(root/'pair_audit.csv',index=False)
    performance=[];differences=[]
    for variant in ['adaptive',*new]:
        for split,subset in (('all',seeds),('development',[s for s in seeds if s<60]),('holdout',[s for s in seeds if s>=60])):
            if not subset:continue
            for scene in scenes:
                a=R[(R.scene==scene)&(R.variant==variant)&R.seed.isin(subset)].set_index('seed')
                b=R[(R.scene==scene)&(R.variant=='fixed')&R.seed.isin(subset)].set_index('seed')
                performance.extend(dict(variant=variant,split=split,scene=scene,**r) for r in screen(a,b,scene))
        for reference in ('adaptive','fixed'):
            for scene in scenes:
                a=R[(R.scene==scene)&(R.variant==variant)].set_index('seed')
                b=R[(R.scene==scene)&(R.variant==reference)].set_index('seed')
                for metric in ('loaded_mae','speed_dip_rpm','load_recovery_ms','unload_peak_rpm','unload_recovery_ms','compensation_abs_mean_a','iq_peak_a','integrator_peak_a'):
                    delta=(a[metric]-b[metric]).dropna()
                    differences.append(dict(variant=variant,reference=reference,scene=scene,metric=metric,n=len(delta),
                        mean=delta.mean(),sample_std=delta.std(),improved=int((delta<0).sum()),worsened=int((delta>0).sum()),equal=int((delta==0).sum())))
    pd.DataFrame(performance).to_csv(root/'performance_screen.csv',index=False)
    pd.DataFrame(differences).to_csv(root/'paired_differences.csv',index=False)
    passed={v:all(x['passed'] for x in performance if x['variant']==v) for v in ['adaptive',*new]}
    result=dict(records=len(records),new_runs=len(new)*len(scenes)*len(seeds),reference_runs=len(refs),source_pins=pins,
        reference_hashes_pass=refs_ok,paired_conditions_pass=all(x['identical_actual_conditions'] for x in pairs),
        failed_checks=failures,performance_pass=passed,performance_failures=[x for x in performance if not x['passed']],
        implementation_checks_pass=all(pins.values()) and refs_ok and all(x['identical_actual_conditions'] for x in pairs) and not failures,
        hardware_access=False,physical_performance_validated=False,
        caveat='No electrical FOC or real motor validation. Speed policy fixed. Passing software non-inferiority screen is not proof of superiority.')
    (root/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='source_pins'},indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');report(p.parse_args().root)
