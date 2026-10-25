"""Vectorised independent SOFTWARE audit; use Python with numpy/pandas.
Does not import or call hardware/firmware transport code.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd


def recovery_ms(t,rpm,start,dwell=100):
    good=(t>=start)&(np.abs(rpm-240)<=5)
    hits=np.flatnonzero(np.convolve(good.astype(np.int32),np.ones(dwell,dtype=np.int32),'valid')==dwell)
    return float((t[hits[0]]-start)*1000) if len(hits) else None


def analyse(f,scene,variant):
    t=f.time_s.to_numpy();active=(f.control_mode==3).to_numpy();before=(t>=3)&(t<5)&active
    direction=f.input_direction.to_numpy();rpm=f.omega_true_rad_s.to_numpy()*30/math.pi*direction
    error=np.abs(f.speed_ref_rpm.to_numpy()-f.speed_meas_rpm.to_numpy())
    comp=f.iq_dob_a.to_numpy();gain=f.gain_selected.to_numpy();states=f.feedback_state.to_numpy().astype(int)
    prev_sat=np.r_[False,((f.dob_status.to_numpy().astype(np.int64)&128)!=0)[:-1]]
    ongoing=active&np.r_[False,active[:-1]]
    slew=np.diff(gain)/np.diff(t);same_phase=ongoing[1:]&(f.fsm_state.to_numpy()[1:]==3)&(f.fsm_state.to_numpy()[:-1]==3)
    expected=np.column_stack([f.requested_j_over_kt,f.requested_b_over_kt,f.requested_ic_over_kt])
    consumed=np.column_stack([f.consumed_j_over_kt,f.consumed_b_over_kt,f.consumed_ic_over_kt])
    zero_mode=f.control_mode.isin([0,1]).to_numpy()
    checks=dict(finite=np.isfinite(f.to_numpy()).all(),working_limit=bool((f.iq_limit_a[active]==.5).all()),
        iq_cap=float(np.max(np.abs(f.iq_cmd_a)))<=.500001,
        comp_cap=float(np.max(np.abs(comp)))<=.025001,gain_bounds=bool(((gain>=0)&(gain<=.250001)).all()),
        sum_before_cap=bool(np.allclose(f.iq_raw_a[active],(f.iq_pi_a+f.iq_acc_ff_a+f.iq_friction_a+f.iq_dob_a)[active],atol=2e-6,rtol=0)),
        total_clamp=bool(np.allclose(f.iq_cmd_a[active],np.clip(f.iq_raw_a[active],-.5,.5),atol=1e-7,rtol=0)),
        integrator_bound=float(np.max(np.abs(f.speed_integrator_a)))<=.350001,
        speed_schedule_disabled=bool(((f.schedule_slow==0)&(f.selected_target_rpm==f.base_target_rpm)&(f.input_schedule_enable==0)).all()),
        actual_parameters=bool(np.array_equal(expected,consumed)),
        neutral_zero=bool((f.iq_cmd_a[zero_mode]==0).all()),
        original_contact_recipe=bool(((f.contact_rpm==20)&(f.contact_iq_ma==300)&(f.contact_dwell_ms==250)).all()),
        no_false_contact=bool((~((f.contact_pending!=0)|(f.contact_confirmed!=0))|(f.fixture_contact!=0)).all()),
        saturated_source_cannot_track=bool(np.all(states[prev_sat&active]!=2)),
        only_qualified_source_tracks=bool(np.all(f.feedback_source_qualified[states==2]==1)),
        invalid_points_no_gain_credit=bool((f.gain_credit_us[f.gain_quality_valid==0]==0).all()) if variant=='adaptive' else True)
    if variant=='adaptive':
        checks['gain_scope']=bool((gain[f.fsm_state!=3]==0).all())
        checks['gain_slew']=bool(np.all(slew[same_phase]<=1.0001)&np.all(slew[same_phase]>=-2.5001))
    if variant=='off':checks['zero_off']=bool((comp==0).all()&(gain==0).all())
    if scene=='fault':
        injected=f.input_protection_fault!=0
        checks['fault_priority']=bool(((f.fsm_state[injected]==10)&(f.iq_cmd_a[injected]==0)).all())
    else:checks['no_hard_fault']=bool(((f.fsm_state!=10)&(f.simulation_guard_fault==0)).all())
    if scene=='stop':
        injected=f.input_stop!=0
        checks['stop_priority']=bool(((f.fsm_state[injected]==0)&(f.iq_cmd_a[injected]==0)).all())
    # Independently reconstruct the existing compensation freshness clock.
    now=np.rint(t*1e6).astype(np.int64)+100020;last=np.zeros(len(t),dtype=np.int64)
    last_source=0;clock_ok=True
    for k,state in enumerate(states):
        if state==2:last_source=int(f.gain_observer_source_us.iat[k])
        elif state in (0,1):last_source=0
        age=int(now[k]-last_source) if last_source else None;last[k]=last_source
        if state==3 and (age is None or age>5000):clock_ok=False
        if state==4 and (age is None or not 5000<age<20000):clock_ok=False
        if state==5 and comp[k]!=0:clock_ok=False
        if active[k] and last_source and age>=20000 and abs(comp[k])>1e-9:clock_ok=False
    checks['original_hold_fade_expiry_clock']=clock_ok
    jerk=np.abs(np.diff(f.accel_ref_rpm_s))/np.diff(t)
    checks['strict_jerk']=bool(np.max(jerk[ongoing[1:]],initial=0)<=1000.2)
    def first(mask):
        hits=np.flatnonzero(mask);return float(t[hits[0]]) if len(hits) else None
    quiet=active&(t>=2)
    loaded=(t>=3)&(t<3.6)&active;unload=(t>=5)&(t<6)&active
    metrics=dict(speed_mae=float(np.mean(error[active])) if active.any() else None,
        loaded_mae=float(np.mean(error[before])) if before.any() else None,
        speed_dip_rpm=max(0,float(240-np.min(rpm[loaded]))) if loaded.any() else None,
        load_recovery_ms=recovery_ms(t,np.where(active,rpm,-1000),3),
        unload_peak_rpm=max(0,float(np.max(rpm[unload])-240)) if unload.any() else None,
        unload_recovery_ms=recovery_ms(t,np.where(active,rpm,-1000),5) if scene=='unload' else None,
        iq_peak_a=float(np.max(np.abs(f.iq_cmd_a))),integrator_peak_a=float(np.max(np.abs(f.speed_integrator_a))),
        at_current_cap_ms=int((np.abs(f.iq_cmd_a)>=.499999).sum()),
        saturation_ms=int(((f.dob_status.to_numpy().astype(np.int64)&128)!=0).sum()),
        compensation_abs_mean_a=float(np.mean(np.abs(comp[quiet]))) if quiet.any() else 0,
        compensation_peak_a=float(np.max(np.abs(comp))),gain_mean=float(np.mean(gain[active])) if active.any() else 0,
        gain_peak=float(np.max(gain)),gain_transitions=float(f.gain_transitions.iloc[-1]),
        observer_valid_percent=float(f.dob_valid[active].mean()*100) if active.any() else 0,
        reset_count=float(f.reset_count.iloc[-1]),warmup_marked_ms=int(((f.dob_status.to_numpy().astype(np.int64)&2)!=0).sum()),
        done=bool((f.fsm_state==7).any()),done_s=first(f.fsm_state.to_numpy()==7),
        timeout=bool((f.fsm_state==9).any()),max_jerk=float(np.max(jerk[ongoing[1:]],initial=0)),
        gain_quality_percent=float(f.gain_quality_valid[active].mean()*100) if active.any() else 0)
    return metrics,checks


def report(root):
    root=Path(root);m=json.loads((root/'manifest.json').read_text());c=json.loads((root/'config.json').read_text())
    scenes=c['scenarios'] if isinstance(c['scenarios'],list) else [c['scenarios']]
    seeds=c['seeds'] if isinstance(c['seeds'],list) else [c['seeds']]
    pins={f['path']:hashlib.sha256(Path(f['path']).read_bytes()).hexdigest()==f['sha256']
        for f in m['sources']+m['firmware_unchanged_pins']}
    pins['dll']=hashlib.sha256(Path(m['dll']).read_bytes()).hexdigest()==m['dll_sha256']
    records=[];failures=[];pairs=[]
    for scene in scenes:
        for seed in seeds:
            frames={}
            for variant in c['variants']:
                f=pd.read_csv(root/f'{scene}_seed{seed:03d}_{variant}.csv.gz');frames[variant]=f
                metrics,checks=analyse(f,scene,variant)
                records.append(dict(scene=scene,seed=seed,variant=variant,**metrics))
                failures.extend(dict(scene=scene,seed=seed,variant=variant,check=k) for k,v in checks.items() if not v)
            keys=[k for k in frames['off'] if k.startswith('input_') and k not in ('input_omega_true_rad_s','input_iq_true_a','input_position_deg')]
            keys+=['external_load_a','fixture_angle_deg','fixture_enabled','consumed_j_over_kt','consumed_b_over_kt',
                'consumed_ic_over_kt','consumed_bias_a','consumed_current_tau_s']
            pair_ok=all(np.array_equal(frames['off'][keys].to_numpy(),frames[v][keys].to_numpy()) for v in ('fixed','adaptive'))
            pairs.append(dict(scene=scene,seed=seed,identical_exogenous_and_actual_parameters=pair_ok))
            print('AUDITED',scene,seed,flush=True)
    R=pd.DataFrame(records);R.to_csv(root/'metrics_per_trial.csv',index=False)
    numeric=[k for k in R if k not in ('scene','seed','variant')]
    summary=R.groupby(['scene','variant'])[numeric].agg(['mean','std','count'])
    summary.columns=['_'.join(col) for col in summary.columns];summary.reset_index().to_csv(root/'metrics_mean_std.csv',index=False)
    pd.DataFrame(pairs).to_csv(root/'pair_audit.csv',index=False)
    differences=[];performance=[]
    for scene in scenes:
        a=R[(R.scene==scene)&(R.variant=='adaptive')].set_index('seed');b=R[(R.scene==scene)&(R.variant=='fixed')].set_index('seed')
        for metric in ('loaded_mae','speed_dip_rpm','load_recovery_ms','unload_peak_rpm','unload_recovery_ms',
            'compensation_abs_mean_a','iq_peak_a','integrator_peak_a','saturation_ms','done_s'):
            delta=(a[metric]-b[metric]).dropna()
            differences.append(dict(scene=scene,metric=metric,n=len(delta),adaptive_minus_fixed_mean=delta.mean(),
                sample_std=delta.std(),improved=int((delta<0).sum()),worsened=int((delta>0).sum()),equal=int((delta==0).sum())))
        if scene in ('step','ramp','unload','noise','replay','negative_load'):
            passed=bool(a.loaded_mae.mean()<=b.loaded_mae.mean()*1.05+.1)
            performance.append(dict(scene=scene,criterion='loaded_mae_not_worse_5percent_plus_0.1rpm',passed=passed))
        if scene=='no_load':
            performance.append(dict(scene=scene,criterion='false_compensation_not_worse_0.1mA',passed=bool(a.compensation_abs_mean_a.mean()<=b.compensation_abs_mean_a.mean()+.0001)))
        if scene=='unload':
            performance.append(dict(scene=scene,criterion='unload_peak_not_worse_1rpm',passed=bool(a.unload_peak_rpm.mean()<=b.unload_peak_rpm.mean()+1)))
            performance.append(dict(scene=scene,criterion='unload_recovery_not_worse_50ms',passed=bool(a.unload_recovery_ms.notna().all() and a.unload_recovery_ms.mean()<=b.unload_recovery_ms.mean()+50)))
        if scene in ('contact_early','contact_late'):
            performance.append(dict(scene=scene,criterion='no_paired_completion_loss',passed=bool((~b.done|a.done).all())))
    pd.DataFrame(differences).to_csv(root/'paired_differences.csv',index=False)
    pd.DataFrame(performance).to_csv(root/'performance_screen.csv',index=False)
    result=dict(runs=len(records),source_and_firmware_pins=pins,paired_conditions_pass=all(p['identical_exogenous_and_actual_parameters'] for p in pairs),
        failed_checks=failures,performance_screen=performance,
        implementation_checks_pass=all(pins.values()) and all(p['identical_exogenous_and_actual_parameters'] for p in pairs) and all(f['check']=='strict_jerk' for f in failures),
        performance_screen_pass=all(p['passed'] for p in performance),
        physical_performance_validated=False,hardware_access=False,
        limitations=['Mechanical/software model; not electrical FOC or real tightening validation.',
            'Speed scheduler disabled in all three groups. Combined speed/gain scheduling not validated.',
            'All groups use the same MCU-aligned SAT128 fresh-feedback guard; older software results lacked it.'])
    (root/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='source_and_firmware_pins'},indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');report(parser.parse_args().root)
