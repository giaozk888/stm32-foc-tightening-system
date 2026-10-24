"""One manually selected LD or LQ shot; provisional Rs only, never writes PI.

Default is files-only. Reuses exact existing A and original OFF/ON/OFF flow.
No automatic second axis/retry. A qualified latch proof is still mandatory
for an inductance estimate, even when the operator supplies provisional Rs.
"""
import argparse
import json
from pathlib import Path
import time
import struct
import motor_ident_rs_reject_count_board as selected
import motor_ident_rs75_board as baseline_helper
import motor_ident_reject_board as reject
import motor_ident_timing_report as timing_report
import motor_ident_encoder_timing_board as encoder
import encoder_saved_fault_report

run=selected.run;base=run.base;TMP=run.TMP
IMAGE,ELF,SHA,ELF_SHA=selected.IMAGE,selected.ELF,selected.SHA,selected.ELF_SHA
RESTORE=TMP/'motor-ident-rs-repeat-restore-1792558189146552900.json'
BASE_SHA='9c574f068e64566d6b2a06af95231d4432534f9a505e28dfd6b723d41ace50aa'
RS_OHM=.78
AXIS='LD'
ORIGINAL_MOTION=run.motion
ORIGINAL_DECODE=run.decode_capture


def configure():
    baseline_helper.configure_from(RESTORE,BASE_SHA,860)


def estimate(capture,rs=RS_OHM):
    # Do not call the all-qualified report or label provisional Rs validated.
    result=dict(rs_input_ohm=rs,rs_qualified=False,conditional_on_assumed_rs=True,
        automatic_pi_write=False,pi_suggestion=None,ld=None,lq=None)
    try:
        value=run.analysis.fit_l(capture,rs)
        result[capture['mode'].lower()]=value
    except (run.analysis.Insufficient,KeyError,ValueError) as e:
        result['quality_error']=str(e)
    return result


def extra_readout(board,row):
    for key,cmd in (
        ('current_reject_reply','MOTOR TEST IDENT REJECT'),
        ('timing_failure_reply','MOTOR TEST IDENT TIMING'),
        ('timing_context_reply','MOTOR TEST IDENT TIMING CONTEXT'),
        ('time_policy_reply','MOTOR TEST IDENT TIME POLICY'),
        ('encoder_time_reply','MOTOR TEST IDENT ENCODER TIME')):
        line=board.command(cmd);row[key]=line;row['ident_replies'].append(line)
    f=base.hw.fields(row['current_reject_reply'])
    if any(f.get(k)!=v for k,v in dict(REJECT_MAX='16',RUN_LIMIT='3',TOTAL_STOP='1',RUN_STOP='1').items()):
        raise ValueError('L-axis strict original current admission required')
    if f.get('FIRST')=='1':
        row['first_reject_reply']=board.command('MOTOR TEST IDENT REJECT ROW')
        row['ident_replies'].append(row['first_reject_reply'])
    encoder.policy(row['encoder_time_reply'])
    if base.hw.fields(row['time_policy_reply']).get('L_DT_MAX')!='55':
        raise ValueError('L-axis original continuity policy required')


def extra_decode(row,ram,offset):
    reject.extra_decode(row,ram,offset)  # Strict L limits, not Rs count-only policy.
    row['ident_timing_failure']=timing_report.decode(ram,offset,max_dt_us=55)
    row['encoder_terminal_saved']=encoder_saved_fault_report.decode_saved(row,ELF)
    wire=run.analysis.decode_uart('\n'.join(row['ident_replies']),AXIS)
    ident=row['ident_ram']
    if (wire['status'],wire['fault'],len(wire['rows']))!=(ident['status'],ident['reason'],ident['count']):
        raise ValueError('Terminal UART/RAM mode/status/count mismatch')
    if abs(ident['current_a']-.1)>1e-6 or ident['used']!=1 or ident['confirmed_locked']!=1:
        raise ValueError('L-axis one-shot identity mismatch')
    # UART is scaled. Compare exact integer identity, not rounded float equality.
    for a,b in zip(wire['rows'],row['ident_run']['rows']):
        if any(a[k]!=b[k] for k in ('us','seq','pending_before','mode','status','reason')):
            raise ValueError('Frozen trace UART/RAM row identity mismatch')
    row['conditional_estimate']=estimate(row['ident_run'])
    row['qualified_inductance']=False  # Provisional Rs cannot become formal via this runner.


def motion(board,row):
    row['encoder_time_pre']=encoder.policy(board.command('MOTOR TEST IDENT ENCODER TIME'))
    ORIGINAL_MOTION(board,row,ident_mode=AXIS)


def decode(row):
    ORIGINAL_DECODE(row,ident_mode=AXIS)


def unused_source(path,data):
    """Resume only a captured, proven never-excited confirmed A; no trial request."""
    old=json.loads(path.read_text('utf-8'))
    if (path.resolve().parent!=TMP.resolve() or old.get('mode')!='run' or
        old.get('test',{}).get('mode')!=AXIS or old.get('image_sha256')!=SHA or
        old.get('elf_sha256')!=ELF_SHA or old.get('excitation_attempts')!=0 or
        any(old.get(k) is not True for k in
            ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped never-excited same-axis run required')
    flash=Path(old['final_capture']);ram=Path(old['ram_capture'])
    if flash.resolve().parent!=TMP.resolve() or ram.resolve().parent!=TMP.resolve():
        raise ValueError('Workspace captures required')
    raw=flash.read_bytes();saved_ram=ram.read_bytes();root=base.baseline()
    if (base.old.zero.digest(raw)!=old['final_sha256'] or len(saved_ram)!=0x20000 or
        raw[:0x7e800]!=root[:0x7e800] or raw[0x7f800:]!=root[0x7f800:] or
        raw[0x8000:0x8000+len(data)]!=data or base.old.zero.latest_meta(raw)[2:5]!=(1,0,0) or
        old.get('outputs',{}).get('VTOR')!=0x08008000):
        raise ValueError('Unused confirmed A capture identity mismatch')
    addr,size=base.symbols(ELF)['motor_ident']
    if size!=1740:raise ValueError('Exact unused identification ABI required')
    values=struct.unpack_from('<11I2f8B',saved_ram,addr-0x20000000+1536)
    if values[0]!=0 or any(values[13:]):
        raise ValueError('Identification already used/queued; never retry')
    return flash,raw


def resume_unused(row,name,path,data):
    if not row.get('powered_no_alarm') or not row.get('locked_fixture'):
        raise ValueError('Supervised powered locked-fixture confirmation required')
    source,before=unused_source(path,data)
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;base.old.prior.checkpoint(row,'resume_unused_no_trial_request')
        base.hw.debug(row,[*base.old.zero.off_gate(),
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands(),'reset run','shutdown'])
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        if not any('MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR' in x for x in uart.lines):
            raise RuntimeError('Identification marker absent')
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=base.profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.old.prior.wait_timing(uart,row);row['preflight_pass']=True
        port.close();board=base.TokenRecordedBoard('COM5',row)
        try:motion(board,row)
        finally:board.close()
    finally:
        if port.is_open:
            try:row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as e:row['stop_error']=str(e)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:decode(row)
    if not row.get('acquisition_pass'):
        raise RuntimeError('Identification aborted/insufficient; no retry or next axis')
    row['pass_']=True


def install(axis):
    global AXIS
    if axis not in ('LD','LQ'):raise ValueError('Exactly one axis required')
    AXIS=axis;selected.install()
    run.configure=configure;run.motion=motion;run.decode_capture=decode
    run.EXTRA_READOUT=extra_readout;run.EXTRA_DECODE=extra_decode
    run.COMMAND='MOTOR TEST IDENT %s RS_VALIDATED LOCKED CONFIRM'%axis
    # Wire token is historical syntax only, NOT a claim Rs was qualified.
    run.install()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--axis',choices=('LD','LQ'),required=True)
    m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true')
    m.add_argument('--execute-powered',type=Path)
    m.add_argument('--resume-unused-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-locked-fixture',action='store_true')
    p.add_argument('--operator-present-locked-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_locked_fixture:
        p.error('Fresh OFF/locked fixture confirmation required')
    if (a.execute_powered or a.resume_unused_powered) and not a.operator_present_locked_drive_on_no_alarm_05a:
        p.error('Fresh supervised powered confirmation required')
    install(a.axis);configure();data=selected.image();base.baseline()
    if not (a.stage_off or a.execute_powered or a.resume_unused_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: unchanged A/B860; one '+AXIS+'; provisional Rs=.78; no devices');return 0
    kind='stage' if a.stage_off else 'run' if (a.execute_powered or a.resume_unused_powered) else 'restore'
    name='motor-ident-'+AXIS.lower()+'-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(RESTORE),
        steps=[],commands=[],uart=[],samples=[],postflight={},start_attempts=0,excitation_attempts=0,
        automatic_retry=False,automatic_next_stage=False,friction_enabled=True,locked_fixture=True,
        physical_power_off=a.drive_off_locked_fixture,
        powered_no_alarm=a.operator_present_locked_drive_on_no_alarm_05a,
        rs_input_ohm=RS_OHM,rs_qualified=False,wire_rs_validated_token_is_qualification=False,
        test=dict(mode=AXIS,axis_step_a=[.05,.10],other_axis_a=0,max_us=104000))
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.resume_unused_powered:resume_unused(row,name,a.resume_unused_powered,data)
        elif a.execute_powered:
            staged=json.loads(a.execute_powered.read_text('utf-8'))
            if staged.get('test')!=row['test'] or staged.get('rs_input_ohm')!=RS_OHM:
                raise ValueError('Exact one-axis staged plan required')
            run.execute(row,name,a.execute_powered,data)
        else:base.restore(row,name,a.restore_b_drive_off,data)
    except BaseException as e:
        row.update(pass_=False,failure=str(e))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('COMPLETE: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
