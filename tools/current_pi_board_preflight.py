"""Pinned new-PI HARD-OFF trial only. Files-only unless explicitly selected.

No START, current injection, fault clear or automatic retry. OFF staging and
B restore are separate from supervised powered calibration/computation.
"""
import argparse
import json
from pathlib import Path
import time
import zlib

import friction_fsm_board as base
from speed500_dynamic_acceptance import mailbox

TMP=base.TMP
IMAGE=base.old.ROOT/'foc2_app_a/build/CurrentPiIdentifiedComputeOnly/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='e8541fa04c7b8a9cf1b9df2f00d42dbef0b03273bb467879235a26cea5f1c514'
ELF_SHA='5309493fbbe4b3a9079e92ac90d5471b5f603a20b6d2d4dd94c4f632ce2a58b9'
RESTORE=TMP/'current-pi-hard-off-restore-1792565911926092400.json'
BASE_SHA='f4b7818cfedf2ea84299f6533e31c173a72aca515716311d249aeaf129e271e5'
BASE_META=(1112493908,3,2,0,0,880,228788,224830272,227964,627317606,0,1516210582)


def image():
    data=IMAGE.read_bytes()
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    command=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    if (len(data)!=228788 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any(command.count('-D'+key+'=1')!=1 for key in
            ('FOC_CURRENT_PI_IDENTIFIED_ENABLE','FOC_FAST_REJECT_COMPUTE_ONLY',
             'FOC_ONE_CYCLE_PWM_PIPELINE','FOC_PREEMPT_COMMIT_PROBE','AS5047P_DMA_FOC_FIRST')) or
        '-DCURRENT_PI_CANDIDATE_BANDWIDTH_HZ=300.0f' not in command or
        '-DFOC_PWM_PIPELINE_CLOSED_LOOP=1' in command or
        b'NAME=FAST_CURRENT_REJECT HARD_OFF=1' not in data or b'TRIP_MA=4000' not in data):
        raise ValueError('Exact hard-OFF new-PI BIN/ELF/flags required')
    return data


def configure():
    receipt=json.loads(RESTORE.read_text('utf-8'))
    capture=Path(receipt.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or receipt.get('mode')!='restore' or
        receipt.get('final_sha256')!=BASE_SHA or receipt.get('motor_commands')!=0 or
        any(receipt.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact pinned stopped B restoration required')
    raw=capture.read_bytes();root=base.ROOT_BASE.read_bytes()
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or
        tuple(base.old.zero.latest_meta(raw))!=BASE_META or list(BASE_META)!=receipt.get('metadata') or
        base.old.zero.digest(root)!=base.ROOT_BASE_SHA or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or
        zlib.crc32(raw[0x40000:0x40000+227964])!=627317606 or
        base.old.zero.digest(raw[0x40000:0x40000+227964])!=
            '1fd1afa9156bb72e71d42a16378d1e0a2cc76d167d9037dd5b3a869d63256826'):
        raise ValueError('Pinned B saved Flash identity mismatch')
    off=receipt.get('outputs',{})
    if (off.get('VTOR')!=0x08040000 or not off.get('DHCSR',0)&0x20000 or
        off.get('SD',0x40)&0x40 or off.get('BDTR',0xc000)&0xc000 or off.get('CCER',1)):
        raise ValueError('Pinned B output-off/halt evidence missing')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=BASE_META
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()
    base.IMAGE=IMAGE;base.ELF=ELF;base.SHA=SHA;base.ELF_SHA=ELF_SHA;base.image=image


def profile(line):
    values=base.hw.fields(line)
    if any(values.get(k)!=v for k,v in dict(NAME='FAST_CURRENT_REJECT',HARD_OFF='1',FSM='ORIGINAL').items()):
        raise RuntimeError('Hard-OFF profile not proven; no further operation')
    return values


def zero_report(line):
    """Parse this hard-off fixture's actual protocol, not a newer zero ABI."""
    values=base.hw.fields(line)
    if 'valid' in values:
        return dict(schema='ROBUST_ADMISSION',fields=base.old.zero.zero_fields(line))
    required=('STATE','REASON','NOM','U0','V0','N','RET','RAW_STATE','RAW_REASON')
    if (any(not values.get(k,'').isdigit() for k in required) or
        values['STATE']!='3' or values['REASON']!='0' or values['N']!='4000' or
        any(not 0<=int(values[k])<=4095 for k in ('NOM','U0','V0'))):
        raise ValueError('Incomplete or failed legacy hard-off zero report')
    # Preserve raw contrast failure separately; never invent admission counters.
    return dict(schema='LEGACY_MEDIAN_ZERO_REPORT',fields=values)


def cleanup_uart(uart,row):
    errors=[]
    for key,cmd,timeout in (('stop_ack','STOP',.6),('safe_ack','ANALOG SAFE',.8)):
        try:row[key]=uart.query(cmd,timeout)
        except Exception as error:errors.append(cmd+': '+str(error))
    if errors:row['stop_error']='; '.join(errors)


def ready_state(line):
    values=base.hw.fields(line)
    required=dict(STATE='1',USED='0',QUEUED='0',ARMED='1',ZERO='3',FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0')
    if any(values.get(k)!=v for k,v in required.items()):
        raise RuntimeError('READY/output-off state lost; no excitation')
    return values


def wait_ready_window(uart,row,clock=time.monotonic):
    """No dependence on optional/best-effort MonitorTask prints.

    Final DWT/CCR acceptance uses exact-image frozen RAM, not guessed UART
    counters. No protection/timing threshold is changed or skipped.
    """
    start=clock();end=start+5.;next_status=start;observations=[]
    while clock()<end:
        uart.poll(min(.05,max(0.,end-clock())))
        if clock()>=next_status:
            values=ready_state(uart.query('MOTOR TEST STATUS',.6))
            observations.append(dict(elapsed_s=clock()-start,state=values))
            next_status=clock()+.5
    row['ready_observation']=observations
    if len(observations)<8 or observations[-1]['elapsed_s']-observations[0]['elapsed_s']<4.:
        raise RuntimeError('Insufficient fresh READY/output-off observation window')
    row['preflight_basis']='UART_READY_5S_PLUS_SAME_SESSION_FROZEN_RAM_TIMING'


def accept_snapshot(row):
    snap=row.get('snapshot',{});timing=snap.get('timing',{});fault=snap.get('first_fault',{})
    if (row.get('preflight_pass') is not True or
        row.get('outputs',{}).get('VTOR')!=0x08008000 or fault.get('valid')!=0 or
        not 0<timing.get('wall_max_us',0)<50 or timing.get('deadline_miss')!=0 or
        timing.get('actual_late_count')!=0 or timing.get('actual_margin_min_us',0)<=1 or
        timing.get('actual_commit_count',0)<100000 or snap.get('cur_confirm',{}).get('fault')!=0):
        raise RuntimeError('Hard-OFF timing/fault snapshot did not pass; no excitation')
    row['pass_']=True


def execute(row,name,path,data):
    if row.get('powered_no_alarm') is not True:raise ValueError('Fresh supervised ON/no-alarm state required')
    source,before=base.staged(path,data)
    port=base.support.support.open_port();uart=base.TokenConsole(port,row)
    try:
        row['hardware_attempted']=True;base.old.prior.checkpoint(row,'hard_off_trial_intent')
        base.hw.debug(row,[*base.old.zero.off_gate(),
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*base.hw.off_commands(),
            *base.hw.write_mailbox(mailbox(2,2,1,len(data),zlib.crc32(data))),
            'reset run','shutdown'])
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        row['zero_reply']=uart.query('MOTOR TEST ZERO')
        row['zero']=zero_report(row['zero_reply'])
        row['profile']=profile(uart.query('MOTOR TEST PROFILE'))
        wait_ready_window(uart,row)
        row['preflight_pass']=True
        for cmd in ('MOTOR TEST TIMING','MOTOR TEST FAULT','FW STATUS','STATUS'):
            row['postflight'][cmd]=uart.query(cmd)
    finally:
        if port.is_open:
            cleanup_uart(uart,row)
            port.close()
        if row.get('hardware_attempted'):base.old.capture_stopped(row,name,before,elf=ELF)
    if row.get('stop_error'):raise RuntimeError('UART shutdown acknowledgement absent')
    accept_snapshot(row)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-locked-fixture',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_locked_fixture:p.error('Fresh OFF required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh supervised ON required')
    configure();data=image();base.baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: hard-OFF identified PI, pinned B preserved; no devices');return 0
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='current-pi-hard-off-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(RESTORE),baseline_sha256=BASE_SHA,steps=[],commands=[],uart=[],samples=[],
        postflight={},start_attempts=0,excitation_attempts=0,motor_commands=0,automatic_retry=False,
        hard_off=True,physical_power_off=a.drive_off_locked_fixture,
        powered_no_alarm=a.operator_present_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:execute(row,name,a.execute_powered,data)
        else:base.restore(row,name,a.restore_b_drive_off,data)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
