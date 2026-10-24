"""Exactly five supervised same-image Ka=2.79e-5 runs. Files only by default."""
import argparse
import json
from pathlib import Path
import statistics
import time
import ka279_board as board

base=board.base;prior=board.gain.prior;TMP=board.TMP
ROOT_RESTORE=TMP/'ka279-restore-1792659231533240400.json'
RUNS=5


def summarize(runs):
    if any(r['metrics'].get('manual_ka')!=board.KA for r in runs):
        raise ValueError('Mixed Ka values cannot be five fixed repeats')
    names=('accel_mae_rpm','cruise_mae_rpm','low_speed_mae_rpm','overshoot_rpm',
        'stable_motion_delay_ms','settling_time_ms','iq_ref_peak_a','iq_meas_peak_a',
        'integrator_peak_a','pi_peak_a','saturation_ms','tail_mean_rpm',
        'foc_max_us','actual_margin_min_us','deadline_miss','ccr_late','uart_dropped_bytes',
        'max_abs_ff_a','aw_limited_samples','unexpected_aw_samples')
    metrics={}
    for name in names:
        values=[r['metrics'][name] for r in runs
                if isinstance(r['metrics'].get(name),(int,float)) and not isinstance(r['metrics'][name],bool)]
        metrics[name]=dict(n=len(values),missing=len(runs)-len(values),
            mean=statistics.mean(values) if values else None,
            sd=statistics.stdev(values) if len(values)>1 else None,
            min=min(values) if values else None,max=max(values) if values else None)
    return dict(completed=len(runs)==RUNS,runs=len(runs),manual_ka=board.KA,
        metrics=metrics,qualified_identification=False,automatic_parameter_write=False,
        qualification='Exactly five fixed ON observations. No contemporaneous OFF group; no causal Ka improvement claim. Rank acceleration by full commanded acceleration MAE, not stable-motion time. Missing settling values remain missing.')


def execute(path,parent):
    if not parent.get('operator_present_whole_batch'):
        raise ValueError('Fresh whole-five-run supervised powered confirmation required')
    plan=json.loads(path.read_text())
    if plan.get('batch_runs')!=RUNS or plan.get('manual_ka')!=board.KA:
        raise ValueError('Exact fixed five-run Ka plan required')
    base.staged(path,board.image())
    previous=None
    for i in range(1,RUNS+1):
        name='ka279-repeat-run-'+str(time.time_ns())
        row=prior.new_run(name,parent,False,i)
        row.update(manual_ka=board.KA,qualified_identification=False,automatic_parameter_write=False,
            speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300)
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        prior.checkpoint(parent,'run_'+str(i)+'_intent');prior.checkpoint(row,'prepared')
        print('KA279 RUN %d/5'%i,flush=True)
        try:
            if previous is None:
                board.execute(row,name,path,board.image())
            else:
                # Original same-image confirmed-A reset/calibration/preflight,
                # protected one START and capture owner. Never a fault retry.
                board.classify(previous)
                prior.next_run(row,name,previous)
                row['metrics']=board.classify(row)
                row['historical_reference']=board.comparison(row)
                row.update(pass_=True,acquisition_complete=True,tightening_success=False)
            prior.checkpoint(row,'safe_acquisition_complete')
            parent['runs'].append(dict(receipt_path=row['receipt_path'],metrics=row['metrics']))
            parent['summary']=summarize(parent['runs']);prior.checkpoint(parent,'run_'+str(i)+'_saved')
            print('ACQUIRED %d/5 %s'%(i,json.dumps(row['metrics'])),flush=True)
            previous=row
        except BaseException as error:
            row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            prior.checkpoint(row,'batch_stopped_no_retry');raise
    parent.update(pass_=True,final_outputs_off=previous['final_outputs_off'],
                  final_cpu_halted=previous['final_cpu_halted'])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-five',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:
        p.error('Fresh OFF required')
    if a.execute_five and not a.operator_present_whole_batch_drive_on_no_alarm_05a:
        p.error('Fresh whole-batch powered confirmation required')
    source=a.execute_five or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=board.setup(selected)
    if not(a.prepare_off or source):print('OFFLINE PASS: five fixed Ka279 runs; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'batch'
    name='ka279-repeat-'+mode+'-'+str(time.time_ns())
    parent=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},runs=[],attempts=[],image_sha256=board.SHA,elf_sha256=board.ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),manual_ka=board.KA,batch_runs=RUNS,
        friction_enabled=True,bemf_enabled=False,automatic_retry=False,automatic_parameter_write=False,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    prior.checkpoint(parent,'prepared')
    try:
        if a.prepare_off:base.stage(parent,name,data)
        elif a.restore_b_drive_off:base.restore(parent,name,source,data)
        else:execute(source,parent)
    except BaseException as error:
        parent['failure']=str(error)
        if parent.get('hardware_attempted') and not parent.get('final_cpu_halted'):
            try:base.hw.emergency_off(parent,TMP/(name+'-failed.bin'))
            except Exception as off:parent['cleanup_error']=str(off)
    if mode=='batch':parent['summary']=summarize(parent['runs'])
    prior.checkpoint(parent,'complete' if parent['pass_'] else 'stopped')
    print(('PASS: ' if parent['pass_'] else 'STOPPED: ')+parent['receipt_path'],flush=True)
    if parent.get('failure'):print(parent['failure'],flush=True)
    return 0 if parent['pass_'] else 1

if __name__=='__main__':raise SystemExit(main())
