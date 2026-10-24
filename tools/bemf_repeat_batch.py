"""Exactly OFF/ON/OFF/ON/OFF/ON on the same fitted BEMF A, no automatic retry.

Default files-only. Each run has a fresh protected boot/calibration/preflight.
No firmware, PI, threshold, recipe, or B application changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import bemf_fitted_fsm_board as fitted
from dq_repeat_batch import summarize

base=fitted.base
TMP=base.TMP
ROOT_RESTORE=TMP/'bemf-fitted-restore-1792642797970003500.json'
ORDER=(False,True,False,True,False,True)
EXPECTED_TERMINAL='FSM terminal RUNDOWN_TIMEOUT; no-load observation is not successful tightening; no retry'


class BatchBoard(fitted.BemfBoard):
    # Same sparse 2Hz query load in BOTH modes; not a controller frequency.
    query_interval_s=.5


def setup(path):
    fitted.configure(path)
    fitted.image();base.baseline()
    base.TokenRecordedBoard=BatchBoard


def checkpoint(row,phase):base.old.prior.checkpoint(row,phase)


def metrics(row):
    result=fitted.classify(row)
    p=row.get('friction_metrics',{}).get('POS',{});aff=row.get('accel_ff_metrics',{})
    if p.get('N')!=8000 or aff.get('N')!=8000:
        raise RuntimeError('Incomplete original 8s aggregate; stop, no invented averages')
    row['result']=result
    return dict(mode='ON' if row['bemf_enabled'] else 'OFF',
        stable_motion_delay_ms=p['START_MS'] if p['START_MS']>=0 else None,
        accel_mae_rpm=aff['ACC_MAE_MRPM']/1000 if aff['ACC_MAE_MRPM']>=0 else None,
        cruise_mae_rpm=p['CRUISE_MAE_MRPM']/1000 if p['CRUISE_MAE_MRPM']>=0 else None,
        low_speed_mae_rpm=p['LOW_MAE_MRPM']/1000 if p['LOW_MAE_MRPM']>=0 else None,
        overshoot_rpm=aff['OV_MRPM']/1000,
        settling_time_ms=aff['SETTLE_MS'] if aff['SETTLE_MS']>=0 else None,
        iq_ref_peak_a=p['IQ_REF_PEAK_MA']/1000,iq_meas_peak_a=p['IQ_MEAS_PEAK_MA']/1000,
        integrator_peak_a=p['I_PEAK_MA']/1000,pi_peak_a=p['PI_PEAK_MA']/1000,
        saturation_ms=aff['SAT_MS'],tail_mean_rpm=row['speed_summary']['tail_mean_rpm'],
        foc_max_us=result['foc_max_us'],actual_margin_min_us=result['actual_margin_min_us'],
        deadline_miss=result['deadline_miss'],ccr_late=result['ccr_late'],
        uart_dropped_bytes=result['uart_dropped_bytes'],
        bemf_observed_peak_v=result['bemf_abs_observed_peak_v'],
        zero_u=row['zero']['zero_u'],zero_v=row['zero']['zero_v'])


def next_run(row,name,previous):
    metrics(previous) # Must prove protection, closure, and full aggregates first.
    source=Path(previous['final_capture']);before=source.read_bytes();meta=base.old.zero.latest_meta(before)
    if (hashlib.sha256(before).hexdigest()!=previous['final_sha256'] or
        meta[2:5]!=(1,0,0) or before[0x8000:0x8000+fitted.SIZE]!=fitted.image()):
        raise ValueError('Exact healthy confirmed-A capture required; no fault recovery')
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;checkpoint(row,'planned_confirmed_A_reset_no_START')
        base.hw.debug(row,[*base.old.zero.off_gate(),
            'if {[mrw 0xE000ED08] != 0x08008000} {error "Expected stopped A"}',
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands(),'reset run','shutdown'])
        row['reset_kind']='next planned confirmed-A run, no mailbox/programming'
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        if not any('INTENT_FSM_CANDIDATE; manual START only' in line for line in uart.lines):
            raise RuntimeError('Wrong startup marker; no START')
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=base.profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.old.prior.wait_timing(uart,row);row['preflight_pass']=True
        checkpoint(row,'preflight_pass');port.close()
        board=BatchBoard('COM5',row)
        try:fitted.motion(board,row)
        finally:board.close()
    finally:
        if port.is_open:
            try:row['stop_ack']=uart.query('STOP',.6);row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as e:row['stop_error']=str(e)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=fitted.ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:fitted.decode(row)


def new_run(name,parent,on,index):
    return dict(mode='run',pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},image_sha256=fitted.SHA,elf_sha256=fitted.ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),baseline_sha256=base.BASE_SHA,
        start_attempts=0,powered_no_alarm=True,friction_enabled=True,bemf_enabled=on,
        psi_f_wb=fitted.PSI_WB,host_max_seconds=base.HOST_MAX_SECONDS,automatic_retry=False,
        batch_parent=parent['receipt_path'],batch_index=index,query_interval_s=BatchBoard.query_interval_s)


def execute(plan_path,parent):
    if not parent.get('operator_present_whole_batch'):
        raise ValueError('Fresh whole-batch powered confirmation required')
    plan=json.loads(plan_path.read_text())
    if plan.get('batch_order')!=list(ORDER) or plan.get('batch_runs')!=6:
        raise ValueError('Exact six-run readiness plan required')
    base.staged(plan_path,fitted.image())
    previous=None
    for index,on in enumerate(ORDER,1):
        name='bemf-repeat-run-'+str(time.time_ns());row=new_run(name,parent,on,index)
        parent['attempts'].append(row['receipt_path']);checkpoint(parent,'run_'+str(index)+'_intent')
        checkpoint(row,'prepared');print('BEMF RUN %d/6 %s'%(index,'ON' if on else 'OFF'),flush=True)
        try:
            if previous is None:
                try:base.execute(row,name,plan_path,fitted.image())
                except RuntimeError as error:
                    if str(error)!=EXPECTED_TERMINAL:raise
                    row['natural_terminal_note']=str(error)
            else:next_run(row,name,previous)
            row['metrics']=metrics(row);row['acquisition_complete']=True;row['tightening_success']=False
            checkpoint(row,'natural_no_load_timeout_acquired')
            parent['runs'].append(dict(receipt_path=row['receipt_path'],metrics=row['metrics']))
            parent['summary']=summarize(parent['runs']);checkpoint(parent,'run_'+str(index)+'_saved')
            print('ACQUIRED %d/6 %s'%(index,json.dumps(row['metrics'])),flush=True)
            previous=row
        except BaseException as error:
            row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            checkpoint(row,'batch_stopped_no_retry')
            parent['last_run']=row['receipt_path'];raise
        parent['last_run']=row['receipt_path']
    parent['pass_']=True;parent['summary']=summarize(parent['runs'])
    parent['final_outputs_off']=previous['final_outputs_off'];parent['final_cpu_halted']=previous['final_cpu_halted']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-six',type=Path)
    p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if a.prepare_off and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF fixture required')
    if a.execute_six and not a.operator_present_whole_batch_drive_on_no_alarm_05a:
        p.error('Fresh supervised powered whole-batch confirmation required')
    plan=json.loads(a.execute_six.read_text()) if a.execute_six else None
    selected=a.baseline_restore or (Path(plan['baseline_restore_receipt']) if plan else ROOT_RESTORE)
    setup(selected)
    if not (a.prepare_off or a.execute_six):
        print('OFFLINE PASS: same fitted A, exactly OFF/ON x3, no devices');return 0
    mode='stage' if a.prepare_off else 'batch';name='bemf-repeat-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],
        postflight={},runs=[],attempts=[],image_sha256=fitted.SHA,elf_sha256=fitted.ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),friction_enabled=True,
        bemf_enabled=False,physical_power_off=a.drive_off_unlocked_no_load_fixed,automatic_retry=False,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    checkpoint(row,'prepared')
    try:
        if a.prepare_off:
            base.stage(row,name,fitted.image());row['batch_order']=list(ORDER);row['batch_runs']=6
        else:execute(a.execute_six,row)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    if mode=='batch':row['summary']=summarize(row['runs'])
    checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
