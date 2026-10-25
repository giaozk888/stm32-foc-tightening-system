"""Independent CSV audit/metrics for software-only RUNDOWN speed adaptation."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics


def first(rows, predicate):
    return next((r['time_s'] for r in rows if predicate(r)), None)


def mean(values):
    return statistics.mean(values) if values else None


def settled_after(rows, begin=5, dwell=100):
    start=None;count=0
    for r in rows:
        if r['time_s']<begin:continue
        good=r['control_mode']==3 and abs(abs(r['omega_true_rad_s'])*30/math.pi-240)<=5
        if good:
            if start is None:start=r['time_s']
            count+=1
            if count>=dwell:return (start-begin)*1000
        else:start=None;count=0
    return None


def analyse(path):
    with gzip.open(path, 'rt', newline='') as handle:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(handle)]
    assert len(rows) == 10001 and all(math.isfinite(v) for r in rows for v in r.values())
    run = [r for r in rows if r['fsm_state'] in (2, 3, 4) and r['control_mode'] == 3]
    uniform = [r for r in run if r['time_s'] >= 2]
    contact = first(rows, lambda r: r['fixture_contact'] != 0)
    confirmed = first(rows, lambda r: r['contact_confirmed'] != 0)
    contact_attempt = first(rows, lambda r: r['contact_pending'] != 0)
    done = first(rows, lambda r: r['fsm_state'] == 7)
    slow = first(rows, lambda r: r['schedule_slow'] != 0)
    # No fiction that lower tracking error alone is better: retain original
    # recipe-speed deficit, physical travel and completion time too.
    impact = next((rows[max(0, i-1)]['omega_true_rad_s'] * 30 / math.pi
                   for i,r in enumerate(rows) if r['fixture_contact'] != 0), None)
    policy_enabled = rows[0]['schedule_enabled'] != 0
    checks = dict(
        current_limit=all(abs(r['iq_cmd_a']) <= .500001 for r in rows),
        total_raw_clamped=all(abs(r['iq_cmd_a']) <= abs(r['iq_raw_a']) + 1e-7 for r in run),
        phase_only=all(abs(r['selected_target_rpm']-r['base_target_rpm']) < 1e-6 for r in rows if r['fsm_state'] != 3),
        target_bounds=all(abs(r['selected_target_rpm']) <= abs(r['base_target_rpm']) + 1e-6 for r in rows),
        target_above_contact=all(abs(r['selected_target_rpm']) >= 120-1e-5 for r in rows if r['schedule_slow']),
        unchanged_iq_limit=all(r['iq_limit_a'] == .5 for r in rows if r['control_mode'] in (3,4)),
        unchanged_dob_gain=all(r['dob_gain'] == .25 for r in rows),
        no_early_contact=contact_attempt is None or (contact is not None and contact_attempt >= contact-.0011),
        confirmed_after_contact=confirmed is None or (contact is not None and confirmed >= contact),
        off_identity=policy_enabled or all(r['base_target_rpm'] == r['selected_target_rpm'] for r in rows),
        accel_limit=all(abs(r['accel_ref_rpm_s']) <= 200.01 for r in run),
        jerk_limit=all(abs(b['accel_ref_rpm_s']-a['accel_ref_rpm_s']) <= 1.0002
                       for a,b in zip(rows,rows[1:]) if a['control_mode']==b['control_mode']==3),
        stop_fault_zero=all(r['iq_cmd_a']==0 for r in rows if r['input_stop'] or r['input_protection_fault']),
        no_load_no_slow=not ('no_load_' in path.name or 'spike_' in path.name) or all(r['schedule_slow']==0 for r in rows),
    )
    saturation = sum(abs(r['iq_raw_a']-r['iq_cmd_a']) > 1e-7 for r in run)
    metric = dict(enabled=int(policy_enabled),slow_first_s=slow,fixture_contact_s=contact,
        contact_attempt_s=contact_attempt,confirmed_s=confirmed,done_s=done,
        completed=int(done is not None),missed_contact=int(rows[0]['fixture_enabled'] and confirmed is None),
        false_contact=int(not checks['no_early_contact']),
        contact_entry_speed_rpm=abs(impact) if impact is not None else None,
        speed_mae_to_shaped_ref=mean([abs(r['speed_meas_rpm']-r['speed_ref_rpm']) for r in uniform]),
        mean_rpm=mean([abs(r['omega_true_rad_s'])*30/math.pi for r in uniform]),
        recipe_speed_deficit_rpm=mean([max(0,240-abs(r['omega_true_rad_s'])*30/math.pi) for r in uniform]),
        minimum_rpm=min((abs(r['omega_true_rad_s'])*30/math.pi for r in uniform),default=None),
        iq_peak_a=max(abs(r['iq_cmd_a']) for r in rows),integrator_peak_a=max(abs(r['speed_integrator_a']) for r in rows),
        saturation_ms=saturation,schedule_transitions=rows[-1]['schedule_transitions'],
        unload_to_recipe_recovery_ms=settled_after(rows) if 'unload_' in path.name else None,
        peak_above_recipe_rpm=max((max(0,abs(r['omega_true_rad_s'])*30/math.pi-240) for r in uniform),default=0),
        last_outcome=rows[-2]['fsm_outcome'],last_reason=rows[-2]['fsm_reason'],
        dob_valid_rate=mean([r['dob_valid'] for r in uniform]),
        final_travel_deg=rows[-1]['travel_true_deg'],
        slow_total_ms=sum(r['schedule_slow'] != 0 for r in rows),
        false_no_load_slow_ms=sum(r['schedule_slow'] != 0 for r in rows) if 'no_load_' in path.name or 'spike_' in path.name else None)
    return rows, metric, checks


def report(root):
    config = json.loads((root/'config.json').read_text());manifest=json.loads((root/'manifest.json').read_text())
    complete=json.loads((root/'report.json').read_text());assert complete['completed']
    if isinstance(config['seeds'], (int,float)):config['seeds']=[int(config['seeds'])]
    for source in manifest['sources']:
        path=Path(source['path'])
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:
            # Later opt-in firmware ports may change the working tree. Only
            # an exact hash-matched original snapshot can satisfy that pin.
            relative=path.relative_to(Path(__file__).resolve().parents[1])
            path=root/'frozen_sources'/relative
        assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==source['sha256'],source['path']
    metrics=[];failures=[];pairs=[]
    for scenario in config['scenarios']:
        for seed in config['seeds']:
            trials=[]
            for enabled in (0,1):
                path=root/f'{scenario}_seed{seed:03d}_enabled{enabled}.csv.gz'
                rows,metric,checks=analyse(path);metric.update(scenario=scenario,seed=seed)
                metrics.append(metric);trials.append((rows,metric,checks))
                failures += [dict(scenario=scenario,seed=seed,enabled=enabled,check=k) for k,v in checks.items() if not v]
            a,b=trials
            keys=['input_target_rpm','input_speed_noise_rpm','input_iq_noise_a','input_id_meas_a','input_current_valid',
                  'input_voltage_sat','input_encoder_age_us','input_running','input_direction','input_stop',
                  'input_protection_fault','external_load_a','fixture_angle_deg','fixture_enabled',
                  'plant_j_over_kt','plant_b_over_kt','plant_ic_over_kt']
            assert all(x[k]==y[k] for x,y in zip(a[0],b[0]) for k in keys),'Unpaired external inputs'
            if b[1]['missed_contact']>a[1]['missed_contact']:
                failures.append(dict(scenario=scenario,seed=seed,check='new_missed_contact'))
            if b[1]['last_reason'] not in (0,7) and b[1]['last_reason']!=a[1]['last_reason']:
                failures.append(dict(scenario=scenario,seed=seed,check='new_process_failure'))
            delta=dict(scenario=scenario,seed=seed)
            for k in ('saturation_ms','iq_peak_a','speed_mae_to_shaped_ref','recipe_speed_deficit_rpm','final_travel_deg','done_s','contact_entry_speed_rpm'):
                delta[k+'_on_minus_off']=b[1][k]-a[1][k] if b[1][k] is not None and a[1][k] is not None else None
            pairs.append(delta)
            print('AUDIT',scenario,seed,flush=True)
    def write_csv(name,data):
        with (root/name).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=data[0]);writer.writeheader();writer.writerows(data)
    write_csv('metrics_per_trial.csv',metrics);write_csv('paired_differences.csv',pairs)
    summaries=[]
    for scenario in config['scenarios']:
        for enabled in (0,1):
            group=[m for m in metrics if m['scenario']==scenario and m['enabled']==enabled];s=dict(scenario=scenario,enabled=enabled,n=len(group))
            for key in metrics[0]:
                if key in ('scenario','enabled','seed'):continue
                vals=[m[key] for m in group if m[key] is not None]
                s[key+'_mean']=statistics.mean(vals) if vals else None
                s[key+'_std']=statistics.stdev(vals) if len(vals)>1 else 0 if vals else None
            summaries.append(s)
    write_csv('metrics_mean_std.csv',summaries)
    result=dict(completed=True,runs=len(metrics),repeats=config['repeats'],safety_and_phase_checks_passed=not failures,
        failed=failures,all_failures_retained=True,paired_exogenous_identical=True,source_hashes_unchanged=True,
        hardware_access=False,physical_performance_validated=False,
        scope='Software mechanical model + original C FSM/controller; current lag assumption, not electrical FOC verification',
        summaries=summaries)
    (root/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(runs=len(metrics),failed=failures),indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    report(parser.parse_args().root)
