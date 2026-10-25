"""Independent files-only audit of paired Simulink contact-boundary runs."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics as st
from pathlib import Path
from report_load_speed import settled_after


def read(path):
    with gzip.open(path,'rt',newline='') as stream:
        return [{k:float(v) for k,v in r.items()} for r in csv.DictReader(stream)]


def analyse(rows,revision):
    hold=[(a,b) for a,b in zip(rows,rows[1:]) if b['fsm_state']==4 and b['control_mode']==3 and a['schedule_slow']==1]
    entries=[(a,b) for a,b in zip(rows,rows[1:]) if a['fsm_state']!=4 and b['fsm_state']==4 and b['control_mode']==3 and a['schedule_slow']==1]
    cancels=[(a,b) for a,b in zip(rows,rows[1:]) if a['fsm_state']==4 and b['fsm_state']==3 and a['schedule_slow']==1]
    speed=[r for r in rows if r['control_mode']==3]
    jerk=[abs(b['accel_ref_rpm_s']-a['accel_ref_rpm_s'])/.001 for a,b in zip(rows,rows[1:]) if a['control_mode']==3 and b['control_mode']==3]
    phase_allowed={3,4} if revision=='candidate' else {3}
    checks=dict(finite=all(math.isfinite(x) for r in rows for x in r.values()),
        iq_cap=all(abs(r['iq_cmd_a'])<=.500001 for r in rows),
        dob_cap=all(abs(r['iq_dob_a'])<=.025001 for r in rows),
        active_iq_limit=all(r['iq_limit_a']==.5 for r in rows if r['control_mode'] in (3,4)),
        contact_recipe=all(r['contact_rpm']==20 and r['contact_iq_ma']==300 and r['contact_dwell_ms']==250 for r in rows),
        phase_scope=all(not r['schedule_slow'] or r['fsm_state'] in phase_allowed for r in rows),
        neutral_zero=all(r['iq_cmd_a']==0 for r in rows if r['control_mode'] in (0,1)),
        no_early_contact=all(not r['contact_pending'] or r['fixture_contact'] for r in rows),
        confirmed_after_truth=all(not r['contact_confirmed'] or r['fixture_contact'] for r in rows),
        no_new_hard_fault=not any(r['fsm_state']==10 or r['simulation_guard_fault'] for r in rows),
        strict_jerk=max(jerk,default=0)<=1000.2)
    if revision=='candidate':
        checks['contact_hold_no_target_increase']=all(abs(b['selected_target_rpm'])<=abs(a['selected_target_rpm'])+.00001 for a,b in hold)
        checks['hold_requires_prior_slow']=all(b['contact_held']==0 or a['schedule_slow']==1 for a,b in zip(rows,rows[1:]))
        checks['cancel_retains_slow']=all(b['selected_target_rpm']==a['selected_target_rpm'] and b['schedule_reason']==9 for a,b in cancels)
    def first(key,value):return next((r['time_s'] for r in rows if r[key]==value),None)
    metrics=dict(contact_entries=len(entries),cancel_events=len(cancels),
        target_raise_on_contact=sum(abs(b['selected_target_rpm'])>abs(a['selected_target_rpm'])+.001 for a,b in entries),
        contact_entry_rpm=next((abs(r['omega_true_rad_s'])*30/math.pi for r in rows if r['fixture_contact']),None),
        done=any(r['fsm_state']==7 for r in rows),done_s=first('fsm_state',7),
        timeout=any(r['fsm_state']==9 for r in rows),
        slow_ms=sum(r['schedule_slow'] for r in rows),
        max_iq_a=max(abs(r['iq_cmd_a']) for r in rows),
        iq_sat_ms=sum(abs(r['iq_cmd_a'])>=.499999 for r in speed),
        max_jerk_rpm_s2=max(jerk,default=0),unload_recovery_ms=settled_after(rows))
    return metrics,checks


def report(root):
    root=Path(root);manifest=json.loads((root/'manifest.json').read_text());config=json.loads((root/'config.json').read_text())
    source_checks={f['path']:hashlib.sha256(Path(f['path']).read_bytes()).hexdigest()==f['sha256'] for f in manifest['sources']}
    source_checks['legacy_dll']=hashlib.sha256(Path(manifest['legacy_dll']).read_bytes()).hexdigest()==manifest['legacy_dll_sha256']
    records=[];failures=[];pairs=[]
    scenes=config['scenarios'] if isinstance(config['scenarios'],list) else [config['scenarios']]
    seeds=config['seeds'] if isinstance(config['seeds'],list) else [config['seeds']]
    for scene in scenes:
        for seed in seeds:
            pair=[]
            for rev in ('legacy','candidate'):
                rows=read(root/f'{scene}_seed{seed:03}_{rev}.csv.gz');pair.append(rows)
                metrics,checks=analyse(rows,rev)
                checks['actual_plant_parameters_match_request']=all(
                    r['consumed_j_over_kt']==r['plant_j_over_kt'] and r['consumed_b_over_kt']==r['plant_b_over_kt']
                    and r['consumed_ic_over_kt']==r['plant_ic_over_kt']
                    and math.isclose(r['consumed_bias_a'],manifest['plant'][3],rel_tol=1e-13)
                    and math.isclose(r['consumed_current_tau_s'],manifest['plant'][4],rel_tol=1e-13) for r in rows)
                if scene!='unload':metrics['unload_recovery_ms']=None
                if scene=='fault':
                    checks.pop('no_new_hard_fault')
                    checks['injected_fault_wins']=all(r['fsm_state']==10 and r['iq_cmd_a']==0
                        for r in rows if r['input_protection_fault']!=0)
                    checks['no_fault_before_injection']=not any(r['fsm_state']==10 for r in rows if r['time_s']<4.3)
                if scene=='stop':
                    checks['injected_stop_wins']=all(r['fsm_state']==0 and r['iq_cmd_a']==0
                        for r in rows if r['input_stop']!=0)
                records.append(dict(scene=scene,seed=seed,revision=rev,**metrics))
                failures.extend(dict(scene=scene,seed=seed,revision=rev,check=k) for k,v in checks.items() if not v)
            keys=[k for k in pair[0][0] if k.startswith('input_') and k not in ('input_omega_true_rad_s','input_iq_true_a','input_position_deg')]
            keys+=['external_load_a','fixture_angle_deg','fixture_enabled','plant_j_over_kt','plant_b_over_kt','plant_ic_over_kt']
            keys+=['consumed_j_over_kt','consumed_b_over_kt','consumed_ic_over_kt','consumed_bias_a','consumed_current_tau_s']
            exogenous=all(a[k]==b[k] for a,b in zip(*pair) for k in keys)
            # No effect is permitted before the first held CONTACT_CONFIRM epoch.
            start=next((i for i,r in enumerate(pair[1]) if r.get('contact_held')),len(pair[1]))
            outputs=manifest['legacy_output_names']
            exact_prefix=all(a[k]==b[k] for a,b in zip(pair[0][:start],pair[1][:start]) for k in outputs)
            pairs.append(dict(scene=scene,seed=seed,exogenous_identical=exogenous,prefix_outputs_identical=exact_prefix,first_hold_index=start))
    summary=[]
    for scene in scenes:
        for rev in ('legacy','candidate'):
            values=[r for r in records if r['scene']==scene and r['revision']==rev]
            item=dict(scene=scene,revision=rev,n=len(values),done_count=sum(r['done'] for r in values),timeout_count=sum(r['timeout'] for r in values))
            for key in records[0]:
                if key in ('scene','seed','revision','done','timeout'):continue
                valid=[r[key] for r in values if r[key] is not None]
                item[key+'_n']=len(valid);item[key+'_mean']=st.mean(valid) if valid else None
                item[key+'_std']=st.stdev(valid) if len(valid)>1 else 0 if valid else None
            summary.append(item)
    def write_csv(name,items):
        with (root/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)
    write_csv('contact_metrics.csv',records);write_csv('contact_summary.csv',summary);write_csv('contact_pair_audit.csv',pairs)
    result=dict(runs=len(records),sources=source_checks,report_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        paired_exogenous=all(p['exogenous_identical'] for p in pairs),
        unchanged_before_contact=all(p['prefix_outputs_identical'] for p in pairs),failed_checks=failures,
        boundary_checks_pass=all(source_checks.values()) and all(p['exogenous_identical'] and p['prefix_outputs_identical'] for p in pairs)
            and all(f['check']=='strict_jerk' for f in failures),
        physical_performance_validated=False,hardware_access=False,
        limitations=['Mechanical model only; no electrical FOC deadline or PWM timing validation.',
            'Known late-contact timeout and strict numeric jerk failures are retained, not waived.',
            'contact_cancel fixture deliberately releases; no completion is required in that scenario.'])
    (root/'contact_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='sources'},indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');args=parser.parse_args();report(args.root)
