"""Pinned manual locked-rotor step A/B: OFF stage, ON one batch, OFF B restore.

Default is FILES ONLY. No normal START, PI/threshold write, forced confirmation,
automatic retry or second batch. Original admission, guards and stop are used.
"""
import argparse
import ctypes
import json
from pathlib import Path
import time
import zlib
import current_pi_fsm_board as prior
import current_step_ab_report as analysis

base=prior.base
TMP=base.TMP
IMAGE=base.old.ROOT/'foc2_app_a/build/CurrentStepAbDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='d7b3dd465a113d1f7efcec85fcd472bd8706dbb34566317c5f4ef6b82c2ec9eb'
ELF_SHA='ab126352bac51fb121f3c00319e0771f19ce224484763ca2e125bd93c1dd2a9e'
COMMAND='MOTOR TEST CURRENT STEP AB CONFIRM'
STATUS='MOTOR TEST CURRENT STEP STATUS'


def image():
    data=IMAGE.read_bytes()
    command=next(r['command'] for r in json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
                 if r['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(command)
    if (len(data)!=214300 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any(command.count('-D'+k+'=1')!=1 for k in
            ('FOC_CURRENT_STEP_AB_DIAG','FOC_CURRENT_PI_IDENTIFIED_ENABLE','FOC_PWM_PIPELINE_CLOSED_LOOP',
             'FOC_STARTUP_TRACE','AS5047P_DMA_FOC_FIRST')) or
        any('-D'+k+'=1' in command for k in ('FOC_FAST_REJECT_COMPUTE_ONLY',
            'FOC_TORQUE_CHAIN_DIAG','FOC_MOTOR_IDENTIFICATION_DIAG','FOC_FRICTION_CALIBRATION_DIAG'))):
        raise ValueError('Exact offline-tested step A BIN/ELF/configuration required')
    for marker in (b'CURRENT_STEP_AB_DIAGNOSTIC: LOCK ROTOR',b'NAME=CURRENT_STEP_AB',
                   b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'STARTUP CONFIG ENABLED=1 ROWS=8'):
        if marker not in data:raise ValueError('Diagnostic/protection identity marker missing')
    if base.symbols(ELF)['current_step_ab'][1]!=ctypes.sizeof(analysis.Capture):
        raise ValueError('Diagnostic ABI mismatch')
    return data


def configure(restore_path=None):
    prior.configure()  # Exact stopped B888 root/metadata/application/private proof.
    base.IMAGE=IMAGE;base.ELF=ELF;base.SHA=SHA;base.ELF_SHA=ELF_SHA;base.image=image
    if restore_path is not None:
        # An explicitly selected later OFF restoration must bind this exact
        # image, preserved root B/boot/private data and a halted B entry.
        # Never guess current generation or weaken the live Flash comparison.
        base.configure_baseline(Path(restore_path))


def stage(row,name,data):
    if not row.get('physical_power_off') or not row.get('locked_fixture'):
        raise ValueError('Fresh drive OFF/locked fixture required; no hardware access')
    base.stage(row,name,data)


def expect(line,wanted,label):
    values=base.hw.fields(line)
    if any(values.get(k)!=str(v) for k,v in wanted.items()):
        raise RuntimeError(label+' mismatch; no excitation/retry')
    return values


def profile(line):
    return expect(line,dict(NAME='CURRENT_STEP_AB',FSM='BYPASSED',SPEED_PI=0,
        ID_REF=0,LIMIT_MA=500,MANUAL_BATCH=1),'Exclusive diagnostic profile')


def ready(line):
    return expect(line,dict(STATE=1,USED=0,ZERO=3,FAULT=0,FLAGS=0,SD=0,MOE=0,CCER=0),'Ready/off state')


def motion(board,row,clock=time.monotonic):
    """Single exact firmware-owned batch; no host timing of individual steps."""
    try:
        row['profile_before']=profile(board.command('MOTOR TEST PROFILE'))
        row['filter_before']=base.filter_profile(board.command('MOTOR TEST FILTER'))
        row['ready_before']=ready(board.command('MOTOR TEST STATUS'))
        row['step_before']=expect(board.command(STATUS),dict(STATE=0,USED=0,DONE=0),'Unused step')
        row['adc_before']=expect(board.command('ADC TIMING'),dict(MISS=0,PF=0,DWT=1),'ADC preflight')
        stack=base.motor_stack(board);row['motor_stack']=stack
        if stack.get('VALID')!='1' or int(stack.get('FREE_B','0'))<256:
            raise RuntimeError('Motor stack preflight missing/insufficient')
        ready(board.command('MOTOR TEST STATUS'))
        if row.get('excitation_attempts'):raise RuntimeError('No second batch')
        row['excitation_attempts']=1;base.old.prior.checkpoint(row,'one_batch_command_intent')
        row['excitation_ack']=board.command(COMMAND,.6)
        expect(row['excitation_ack'],dict(ONE_BATCH=1,STEPS=10,LOCKED_ACK=1),'Single batch ACK')
        deadline=clock()+1.5
        while clock()<deadline:
            values=base.hw.fields(board.command(STATUS,.3))
            row.setdefault('step_status_samples',[]).append(values)
            if values.get('STATE') in ('3','4','5'):
                row['step_terminal']=values;break
        if not row.get('step_terminal'):raise TimeoutError('Bounded batch terminal absent; no retry')
    finally:
        # No resend of the excitation command, even on an unknown ACK.
        errors=[]
        for key,cmd in (('stop_ack','MOTOR TEST STOP'),('safe_ack','ANALOG SAFE')):
            try:row[key]=board.command(cmd,.8)
            except Exception as e:errors.append(cmd+': '+str(e))
        if errors:row['stop_error']='; '.join(errors)
    row['safe']=expect(board.command('ANALOG SAFE STATUS'),dict(LATCHED=1,SD=0,MOE=0,FOC=0),'Safe latch')
    row['step_final']=base.hw.fields(board.command(STATUS))
    if row['step_final'].get('STATE') not in ('3','4','5'):raise RuntimeError('Diagnostic not terminal')
    row['step_replies']=[board.command('MOTOR TEST CURRENT STEP METRIC '+str(k)) for k in range(10)]
    row['event_replies']=[board.command('MOTOR TEST CURRENT STEP ROW '+str(k)) for k in range(60)]
    for cmd in ('MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS','ADC TIMING'):
        row['postflight'][cmd]=board.command(cmd)


def decode_capture(row):
    raw=Path(row['final_capture']).read_bytes();ram=Path(row['ram_capture']).read_bytes()
    if (base.old.zero.digest(raw)!=row['final_sha256'] or len(ram)!=0x20000 or
        raw[0x8000:0x8000+len(image())]!=image() or row['outputs'].get('VTOR')!=0x08008000):
        raise ValueError('Same-session A image/RAM identity not proven')
    addr,size=base.symbols(ELF)['current_step_ab']
    capture=ram[addr-0x20000000:addr-0x20000000+size]
    row['ram_sha256']=base.old.zero.digest(ram)
    if not row.get('excitation_attempts'):
        row['step_analysis']=dict(status='NOT_STARTED',reason='No excitation command sent')
    else:
        row['step_analysis']=analysis.decode_capture(capture,row['snapshot'])
    row['report_identity']=dict(halted=row['final_cpu_halted'],outputs_off=row['final_outputs_off'],
        vtor=row['outputs']['VTOR'],elf_sha256=ELF_SHA,image_sha256=SHA,
        ram_sha256=row['ram_sha256'],flash_sha256=row['final_sha256'])


def execute(row,name,path,data):
    if not row.get('powered_no_alarm') or not row.get('locked_fixture'):
        raise ValueError('Fresh powered/no-alarm/operator/locked fixture required; no hardware access')
    source,before=base.staged(path,data)
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;base.old.prior.checkpoint(row,'single_trial_no_START')
        base.hw.debug(row,[*base.old.zero.off_gate(),
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands(),
            *base.hw.write_mailbox(base.mailbox(2,2,1,len(data),zlib.crc32(data))),'reset run','shutdown'])
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.old.prior.wait_timing(uart,row);row['preflight_pass']=True
        base.old.prior.checkpoint(row,'preflight_pass')
        port.close();board=base.TokenRecordedBoard('COM5',row)
        try:motion(board,row)
        finally:board.close()
    finally:
        if port.is_open:
            try:row['safe_ack']=uart.query('ANALOG SAFE',.8)
            except Exception as e:row['stop_error']=str(e)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:decode_capture(row)
    result=row.get('step_analysis',{})
    row['acquisition_completed']=result.get('state') in (3,4) and result.get('completed') in (6,10)
    row['pass_']=bool(row.get('preflight_pass') and row['acquisition_completed'] and
        result.get('timing_qualified') and not row.get('stop_error'))
    if not row['pass_']:raise RuntimeError('Batch incomplete/protection/timing failure; no retry')


def restore(row,name,path,data):
    if not row.get('physical_power_off') or not row.get('locked_fixture'):
        raise ValueError('Fresh drive OFF/fixture required')
    base.restore(row,name,path,data)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--baseline-restore',type=Path,help='Exact successful halted B restoration receipt')
    p.add_argument('--drive-off-locked-fixed',action='store_true')
    p.add_argument('--operator-present-locked-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_locked_fixed:p.error('Fresh OFF/locked fixture required')
    if a.execute_powered and not a.operator_present_locked_drive_on_no_alarm_05a:p.error('Fresh ON/locked/no-alarm supervised fixture required')
    input_path=a.execute_powered or a.restore_b_drive_off
    source=json.loads(input_path.read_text('utf-8')) if input_path else None
    selected=a.baseline_restore or (Path(source['baseline_restore_receipt']) if source else None)
    configure(selected);data=image();base.baseline()
    if not(a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: exact step AB A and B%d baseline; no devices'%base.EXPECT_META[5]);return 0
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='current-step-ab-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),baseline_sha256=base.BASE_SHA,
        physical_power_off=a.drive_off_locked_fixed,powered_no_alarm=a.operator_present_locked_drive_on_no_alarm_05a,
        locked_fixture=True,start_attempts=0,excitation_attempts=0,automatic_retry=False,
        diagnostic='CURRENT_STEP_AB',normal_START_allowed=False,
        plan=dict(max_batch_us=800000,pulse_us=30000,pre_zero_us=20000,post_zero_us=30000,
                  iq_a=list(analysis.TARGETS),positive_quality_gate=True,formal_b_unchanged=True))
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:stage(row,name,data)
        elif a.execute_powered:execute(row,name,a.execute_powered,data)
        else:restore(row,name,a.restore_b_drive_off,data)
    except BaseException as e:
        row.update(pass_=False,failure=str(e))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup:row['cleanup_error']=str(cleanup)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
