"""Exactly 3 OFF / 3 ON supervised runs, alternating; default files only.

Uses original runtime + original START/stop/lease/limits. No parameter writes,
sign sweep, retries, fault clearing or automatic B application execution.
First run: original A/B trial. Remaining planned runs: output-OFF verified
confirmed-A reset, fresh zero/health/timing preflight, exactly one START each.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
import dq_original_runtime_board as runtime

original=runtime.original
base=original.base
TMP=base.TMP
ORDER=(False,True,False,True,False,True)


def setup(receipt):
    original.IMAGE=base.old.ROOT/'foc2_app_a/build/DqOriginalRuntime/foc2.bin'
    original.ELF=original.IMAGE.with_suffix('.elf')
    runtime.configure(Path(receipt));original.image();base.baseline()


def checkpoint(row,phase):base.old.prior.checkpoint(row,phase)


def required_off(row):
    o=row.get('outputs',{})
    return (row.get('final_outputs_off') is True and row.get('final_cpu_halted') is True and
        o.get('VTOR')==0x08008000 and o.get('DHCSR',0)&0x20000 and
        o.get('SD',0x40)&0x40==0 and o.get('BDTR',0xc000)&0xc000==0 and o.get('CCER',1)==0)


def classify(row):
    """Only complete, correctly shut down runs contribute to comparisons.

    Poor speed tracking is quality data, not grounds to hide a run. An
    independent fault / lost stop / wrong image always prevents another run.
    """
    if not required_off(row) or row.get('all_app_private_unchanged') is not True:
        raise RuntimeError('No verified OFF/halted/unchanged closure; stop entire batch')
    if row.get('start_attempts')!=1 or not row.get('preflight_pass'):
        raise RuntimeError('Missing original single START/preflight; stop entire batch')
    fault=base.hw.fields(row.get('postflight',{}).get('MOTOR TEST FAULT',''))
    terminal=row.get('terminal_status',{})
    snap=row.get('snapshot',{});timing=snap.get('timing',{});cf=snap.get('cur_confirm',{})
    encoder=row.get('encoder_saved')
    if (fault.get('VALID')!='0' or fault.get('FLAGS')!='0' or terminal.get('FLT')!='0' or
        terminal.get('CONTACT')!='0' or terminal.get('OUTCOME')!='RUNDOWN_TIMEOUT' or
        row.get('fsm_observation_complete') is not True or
        timing.get('deadline_miss')!=0 or timing.get('actual_late_count')!=0 or
        not 0<timing.get('wall_max_us',0)<50 or timing.get('actual_margin_min_us',0)<=1 or
        cf.get('fault')!=0 or not encoder or encoder['first_fault']['valid'] or
        encoder['counters']['timeouts'] or encoder['counters']['dma_errors'] or
        encoder['counters']['schedule_misses'] or encoder['counters']['control_stale']):
        raise RuntimeError('Protection/terminal/timing/encoder evidence failed; stop entire batch')
    if row.get('token_decode_errors') or row.get('accel_ff_metrics_error') or row.get('friction_metrics_error'):
        raise RuntimeError('Incomplete diagnostic metrics; stop, do not average invented values')
    p=row.get('friction_metrics',{}).get('POS',{})
    aff=row.get('accel_ff_metrics',{})
    if p.get('N')!=8000 or aff.get('N')!=8000:
        raise RuntimeError('Not a full original 8-second window; stop entire batch')
    return dict(mode='ON' if row['dq_enabled'] else 'OFF',
        stable_motion_delay_ms=p['START_MS'] if p['START_MS']>=0 else None,
        accel_mae_rpm=aff['ACC_MAE_MRPM']/1000 if aff['ACC_MAE_MRPM']>=0 else None,
        cruise_mae_rpm=p['CRUISE_MAE_MRPM']/1000 if p['CRUISE_MAE_MRPM']>=0 else None,
        low_speed_mae_rpm=p['LOW_MAE_MRPM']/1000 if p['LOW_MAE_MRPM']>=0 else None,
        overshoot_rpm=aff['OV_MRPM']/1000,
        settling_time_ms=aff['SETTLE_MS'] if aff['SETTLE_MS']>=0 else None,
        iq_ref_peak_a=p['IQ_REF_PEAK_MA']/1000,iq_meas_peak_a=p['IQ_MEAS_PEAK_MA']/1000,
        integrator_peak_a=p['I_PEAK_MA']/1000,pi_peak_a=p['PI_PEAK_MA']/1000,
        tail_mean_rpm=row['speed_summary']['tail_mean_rpm'],
        foc_max_us=timing['wall_max_us'],actual_margin_min_us=timing['actual_margin_min_us'],
        deadline_miss=timing['deadline_miss'],ccr_late=timing['actual_late_count'],
        zero_u=row['zero']['zero_u'],zero_v=row['zero']['zero_v'])


def summarize(rows):
    grouped={}
    for mode in ('OFF','ON'):
        group=[r['metrics'] for r in rows if r.get('metrics',{}).get('mode')==mode]
        metrics={}
        keys=set().union(*(set(g)-{'mode'} for g in group)) if group else set()
        for k in sorted(keys):
            values=[g[k] for g in group if g.get(k) is not None]
            if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in values):
                raise ValueError('Nonfinite measurement')
            metrics[k]=dict(n=len(values),missing=len(group)-len(values),
                mean=statistics.mean(values) if values else None,
                sd=statistics.stdev(values) if len(values)>1 else None,
                min=min(values) if values else None,max=max(values) if values else None)
        grouped[mode]=dict(runs=len(group),metrics=metrics)
    diffs={}
    for k in grouped['ON']['metrics'].keys() & grouped['OFF']['metrics'].keys():
        a=grouped['ON']['metrics'][k]['mean'];b=grouped['OFF']['metrics'][k]['mean']
        diffs[k]=a-b if a is not None and b is not None else None
    return dict(groups=grouped,on_minus_off_mean=diffs,
        conclusion='Descriptive n=3 per group, not statistical causality/torque qualification. Startup is continuous low-speed establishment, not first mechanical movement. Initial rotor angle/temperature not controlled; zero offsets retained.',
        completed=len(rows)==6 and all(grouped[m]['runs']==3 for m in ('OFF','ON')))


def add_decode(row):
    row['ram_sha256']=hashlib.sha256(Path(row['ram_capture']).read_bytes()).hexdigest()
    row['encoder_saved']=original.encoder_report.decode_saved(row,original.ELF)
    row.pop('encoder_decode_error',None)


def next_run(row,name,previous):
    """Reset a VERIFIED healthy confirmed A; never recover a protected fault."""
    classify(previous)
    source=Path(previous['final_capture']);before=source.read_bytes()
    meta=base.old.zero.latest_meta(before)
    if (hashlib.sha256(before).hexdigest()!=previous['final_sha256'] or
        meta[2:5]!=(1,0,0) or before[0x8000:0x8000+len(original.image())]!=original.image()):
        raise ValueError('Exact healthy stopped confirmed-A capture required')
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;checkpoint(row,'planned_confirmed_A_reset_no_START')
        base.hw.debug(row,[*base.old.zero.off_gate(),
            'if {[mrw 0xE000ED08] != 0x08008000} {error "Expected stopped A"}',
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands(),'reset run','shutdown'])
        row['reset_kind']='confirmed-A, no mailbox, no Flash programming'
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        if not any('INTENT_FSM_CANDIDATE; manual START only' in line for line in uart.lines):
            raise RuntimeError('Wrong startup marker; no START')
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=base.profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.old.prior.wait_timing(uart,row);row['preflight_pass']=True
        checkpoint(row,'preflight_pass');port.close()
        board=base.TokenRecordedBoard('COM5',row)
        try:original.motion(board,row)
        finally:board.close()
    finally:
        if port.is_open:
            try:row['stop_ack']=uart.query('STOP',.6);row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as e:row['stop_error']=str(e)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=original.ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:original.decode(row)


def prepare(row,name):
    base.stage(row,name,original.image())
    row['batch_order']=list(ORDER);row['batch_runs']=6;row['per_mode_runs']=3


def execute_batch(plan_path,parent):
    plan=json.loads(plan_path.read_text())
    if plan.get('batch_order')!=list(ORDER) or plan.get('batch_runs')!=6 or plan.get('dq_enabled') is not False:
        raise ValueError('Exact supervised six-run stage required')
    base.staged(plan_path,original.image())
    previous=None
    for i,on in enumerate(ORDER):
        name='dq-repeat-run-'+str(time.time_ns())
        row=dict(mode='run',pass_=False,receipt_path=str(TMP/(name+'.json')),
            image_sha256=original.SHA,elf_sha256=original.ELF_SHA,
            baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),baseline_sha256=base.BASE_SHA,
            steps=[],commands=[],uart=[],samples=[],postflight={},start_attempts=0,
            powered_no_alarm=True,friction_enabled=True,friction_a=.105,dq_enabled=on,
            host_max_seconds=base.HOST_MAX_SECONDS,automatic_retry=False,
            batch_parent=parent['receipt_path'],batch_index=i+1)
        parent['attempts'].append(row['receipt_path']);checkpoint(parent,'run_'+str(i+1)+'_intent')
        checkpoint(row,'prepared')
        print('BATCH RUN %d/6 DQ=%s'%(i+1,'ON' if on else 'OFF'),flush=True)
        try:
            if previous is None:
                try:base.execute(row,name,plan_path,original.image())
                except RuntimeError as e:
                    expected='FSM terminal RUNDOWN_TIMEOUT; no-load observation is not successful tightening; no retry'
                    if str(e)!=expected:raise
                    row['natural_terminal_message']=str(e)  # Keep timeout, not tightening OK.
            else:next_run(row,name,previous)
            add_decode(row)
            row['metrics']=classify(row);row['acquisition_complete']=True
            row['pass_']=False;row['tightening_success']=False
            checkpoint(row,'natural_no_load_timeout_acquired')
            parent['runs'].append(dict(receipt_path=row['receipt_path'],metrics=row['metrics']))
            parent['summary']=summarize(parent['runs']);checkpoint(parent,'run_'+str(i+1)+'_saved')
            print('ACQUIRED %d/6 %s'%(i+1,json.dumps(row['metrics'])),flush=True)
            previous=row
        except BaseException as e:
            row['failure']=str(e)
            if row.get('hardware_attempted') and not required_off(row):
                try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            checkpoint(row,'batch_stopped_no_retry')
            parent['last_run']=row['receipt_path']
            raise
        parent['last_run']=row['receipt_path']
    parent['pass_']=True;parent['summary']=summarize(parent['runs'])
    parent['final_outputs_off']=required_off(previous);parent['final_cpu_halted']=previous['final_cpu_halted']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-six',type=Path)
    p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if a.prepare_off and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF fixture required')
    if a.execute_six and not a.operator_present_whole_batch_drive_on_no_alarm_05a:
        p.error('Operator present whole six-run batch, powered/no alarm/0.5A required')
    plan=json.loads(a.execute_six.read_text()) if a.execute_six else None
    selected=a.baseline_restore or (Path(plan['baseline_restore_receipt']) if plan else None)
    if selected is None:p.error('Exact latest restored-B receipt required')
    setup(selected)
    if not (a.prepare_off or a.execute_six):
        print('OFFLINE PASS: original runtime; six OFF/ON alternating slots only; no devices');return 0
    kind='stage' if a.prepare_off else 'batch'
    name='dq-repeat-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),
        steps=[],commands=[],uart=[],samples=[],postflight={},runs=[],attempts=[],
        image_sha256=original.SHA,elf_sha256=original.ELF_SHA,dq_enabled=False,friction_enabled=True,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),baseline_sha256=base.BASE_SHA,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,automatic_retry=False,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    checkpoint(row,'prepared')
    try:
        if a.prepare_off:prepare(row,name)
        else:execute_batch(a.execute_six,row)
    except BaseException as e:
        row['failure']=str(e);row['pass_']=False
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    if kind=='batch':row['summary']=summarize(row['runs'])
    checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
