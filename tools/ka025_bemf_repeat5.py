"""Five supervised BEMF ON observations at fixed Ka025. Files-only default."""
import argparse
import json
from pathlib import Path
import statistics
import time
import ka025_bemf_board as board

base=board.base
prior=board.gain.prior
RUNS=5


def summarize(runs):
    if any(r['metrics'].get('manual_ka')!=board.KA or
           r['metrics'].get('bemf_enabled') is not True for r in runs):
        raise ValueError('Only fixed Ka025 BEMF ON observations allowed')
    names=('accel_mae_rpm','cruise_mae_rpm','low_speed_mae_rpm','overshoot_rpm',
        'stable_motion_delay_ms','settling_time_ms','iq_ref_peak_a','iq_meas_peak_a',
        'integrator_peak_a','pi_peak_a','saturation_ms','foc_max_us',
        'actual_margin_min_us','deadline_miss','ccr_late','uart_dropped_bytes',
        'bemf_observed_peak_v')
    metrics={}
    for name in names:
        values=[r['metrics'][name] for r in runs
                if isinstance(r['metrics'].get(name),(int,float))
                and not isinstance(r['metrics'][name],bool)]
        metrics[name]=dict(n=len(values),missing=len(runs)-len(values),
            mean=statistics.mean(values) if values else None,
            sd=statistics.stdev(values) if len(values)>1 else None,
            min=min(values) if values else None,max=max(values) if values else None)
    return dict(completed=len(runs)==RUNS,runs=len(runs),manual_ka=board.KA,
        bemf_enabled=True,metrics=metrics,automatic_parameter_write=False,
        qualification='Five ON repeats versus one preceding OFF baseline; unequal groups, descriptive only. Acceleration MAE is primary, stable-motion delay is not physical startup time. Missing settling values stay missing.')


def execute(path,parent):
    if not parent.get('operator_present_whole_batch'):
        raise ValueError('Fresh supervised whole-five-run powered confirmation required')
    plan=json.loads(path.read_text())
    if plan.get('bemf_enabled') is not True or plan.get('manual_ka')!=board.KA:
        raise ValueError('Exact staged BEMF ON Ka025 plan required')
    data=board.image()
    base.staged(path,data)
    previous=None
    for index in range(1,RUNS+1):
        name='ka025-bemf-repeat-run-'+str(time.time_ns())
        row=prior.new_run(name,parent,True,index)
        row.update(manual_ka=board.KA,automatic_parameter_write=False,
            speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300)
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        prior.checkpoint(parent,'run_'+str(index)+'_intent');prior.checkpoint(row,'prepared')
        print('KA025 BEMF ON RUN %d/5'%index,flush=True)
        try:
            if previous is None:
                board.execute(row,name,path,data)
            else:
                prior.metrics(previous) # Real protection and safe closure gate.
                prior.next_run(row,name,previous) # Same confirmed A; no flashing/mailbox.
                row['metrics']=prior.metrics(row)
                row['metrics'].update(manual_ka=board.KA,bemf_enabled=True)
                row.update(pass_=True,acquisition_complete=True,tightening_success=False)
            prior.checkpoint(row,'safe_acquisition_complete')
            parent['runs'].append(dict(receipt_path=row['receipt_path'],metrics=row['metrics']))
            parent['summary']=summarize(parent['runs'])
            prior.checkpoint(parent,'run_'+str(index)+'_saved')
            print('ACQUIRED %d/5 %s'%(index,json.dumps(row['metrics'])),flush=True)
            previous=row
        except BaseException as error:
            row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:base.hw.emergency_off(row,board.TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            prior.checkpoint(row,'batch_stopped_no_retry')
            raise
    parent.update(pass_=True,final_outputs_off=previous['final_outputs_off'],
                  final_cpu_halted=previous['final_cpu_halted'])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute-five',type=Path)
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if a.execute_five and not a.operator_present_whole_batch_drive_on_no_alarm_05a:
        p.error('Fresh whole-batch supervised powered confirmation required')
    if not a.execute_five:
        board.image();print('OFFLINE PASS: fixed Ka025 BEMF ON five runs; no devices');return 0
    plan=json.loads(a.execute_five.read_text())
    board.setup(Path(plan['baseline_restore_receipt']))
    name='ka025-bemf-repeat-batch-'+str(time.time_ns())
    parent=dict(mode='batch',pass_=False,receipt_path=str(board.TMP/(name+'.json')),
        steps=[],commands=[],uart=[],samples=[],postflight={},runs=[],attempts=[],
        image_sha256=board.SHA,elf_sha256=board.ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),manual_ka=board.KA,
        batch_runs=RUNS,bemf_enabled=True,friction_enabled=True,automatic_retry=False,
        automatic_parameter_write=False,operator_present_whole_batch=True)
    prior.checkpoint(parent,'prepared')
    try:execute(a.execute_five,parent)
    except BaseException as error:parent['failure']=str(error)
    parent['summary']=summarize(parent['runs'])
    prior.checkpoint(parent,'complete' if parent['pass_'] else 'stopped')
    print(('PASS: ' if parent['pass_'] else 'STOPPED: ')+parent['receipt_path'],flush=True)
    if parent.get('failure'):print(parent['failure'],flush=True)
    return 0 if parent['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
