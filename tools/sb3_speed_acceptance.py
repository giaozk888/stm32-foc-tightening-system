"""Exact SB3 stage, one no-load SPEED or full-FSM trial, OFF B restore.

Default files only. No protection/recipe-budget edits, SAVE or second START.
The 2s STOP is host-timed; the unchanged independent board lease is 12s.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import sb2_speed_acceptance as old
import voltage_x2_board_test as voltage
from firmware_transfer_iap import fields, image_info
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, off_report, check_off
from original_closed_loop_trial import emergency_off
from loaded_fsm_motion import RecordedBoard, check_profile

TMP=old.TMP
IMAGE=old.ROOT/'foc2_app_a/build/SpeedBrakeTrackTrial/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='8e6e976c4b74f0c0e4ecd961b4b769357ba17cfad24c9a9621301a2fbe98d572'
ELF_SHA='885c9aa261d5df16cb2f0af18ba8023c65d55c8018bfe6ac7f4c88d0d0171d7a'
BASE=TMP/'voltage-x2-restore-1792317681436333200-flash.bin'
BASE_SHA='e44bace196935ec8eb1a25a5d0e37cfdf47647a5abb3837cfe0d36313d684143'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=229036 or old.zero.digest(data)!=SHA or image_info(data)[0]!='A' or
            old.zero.digest(ELF.read_bytes())!=ELF_SHA):
        raise ValueError('Exact offline-tested SB3 BIN/ELF required')
    for marker in (b'SPEED_CTRL=SB3 VLIMIT_MV=1600 ILIMIT_MV=750',
                   b'RPM=20 LEASE_US=12000000',b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4',b'TRIP_MA=4000',b'ZERO CAL valid='):
        if marker not in data: raise ValueError('SB3/protection identity absent')
    return data


def baseline():
    raw=BASE.read_bytes(); before=voltage.baseline(); previous=voltage.image()
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
            old.zero.latest_meta(raw)[2:6]!=(2,0,0,661) or
            raw[0x8000:0x8000+len(previous)]!=previous or raw[:0x8000]!=before[:0x8000] or
            raw[0x40000:0x7e800]!=before[0x40000:0x7e800] or raw[0x7f800:]!=before[0x7f800:]):
        raise ValueError('Exact halted B661 / preceding SB2 A required')
    return raw


def stage(row,name,data):
    before=baseline(); saved=TMP/(name+'-before.bin'); row['hardware_attempted']=True
    debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted preserved B661"}',
        *full_compare_commands(saved,BASE),'shutdown'])
    old.prior.checkpoint(row,'baseline_verified')
    staged=TMP/(name+'-staged.bin'); row['programming_attempted']=True
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=debug(row,[*old.zero.off_gate(),
        *full_compare_commands(TMP/(name+'-recheck.bin'),saved),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
        *off_report(),'halt','shutdown'])
    raw=staged.read_bytes(); old.zero.validate_staged(raw,before,data)
    row.update(pass_=True,staged_capture=str(staged),staged_sha256=old.zero.digest(raw),
        metadata=list(old.zero.latest_meta(raw)),b_and_private_unchanged=True,activation=False,
        outputs=check_off(output,(0,0x08000000)),final_cpu_halted=True,final_outputs_off=True)


def stage_receipt(path,data):
    r=json.loads(path.read_text('utf-8')); capture=Path(r.get('staged_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            r.get('mode')!='stage' or r.get('pass_') is not True or
            r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            not r.get('physical_power_off') or not r.get('motor_connected_fixed')):
        raise ValueError('Exact successful SB3 OFF stage required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=r.get('staged_sha256'): raise ValueError('Stage capture changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


def motion(board,row,full_fsm=False):
    if full_fsm:
        voltage.cycle.fsm.execute(board,row,'A',expected_speed_ctrl='SB3')
    else:
        old.prior.motion(board,row,expected_speed_ctrl='SB3')


def execute(row,name,path,data,full_fsm=False):
    staged,before=stage_receipt(path,data)
    port=old.prior.open_port(); uart=old.prior.JournalConsole(port,row)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_request_intent')
        debug(row,[*old.zero.off_gate(),
            *full_compare_commands(TMP/(name+'-pretrial.bin'),staged),
            'reset halt',*off_commands(),*write_mailbox(mailbox),'reset run','shutdown'])
        row['trial_requests']=1; row['reset_attempts']=1
        old.prior.checkpoint(row,'trial_request_submitted')
        old.prior.wait_health_confirmation(uart,row,fields)
        row['preflight_zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        profile=fields(uart.query('MOTOR TEST PROFILE')); check_profile(profile,'SB3')
        if profile.get('VLIMIT_MV')!='1600' or profile.get('ILIMIT_MV')!='750':
            raise RuntimeError('Wrong voltage/integrator profile; no START')
        old.prior.wait_timing(uart,row); old.prior.checkpoint(row,'preflight_pass')
        port.close()
        board=(voltage.cycle.JournalBoard if full_fsm else RecordedBoard)('COM5',row)
        try: motion(board,row,full_fsm)
        finally: board.close()
    finally:
        if port.is_open: port.close()
        row['startup_uart']=uart.lines
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    snap=row.get('snapshot')
    if (not snap or snap['first_fault']['valid'] or snap['timing']['deadline_miss'] or
            snap['timing']['actual_late_count']):
        raise RuntimeError('Postflight snapshot/protection/timing failure')
    if full_fsm: row['state_machine_pass']=bool(row.get('cycle_pass'))
    row['pass_']=bool(row.get('cycle_pass') if full_fsm else row.get('motion_pass'))


def stopped_receipt(path,data):
    r=json.loads(path.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            r.get('mode') not in ('speed','fsm') or r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            any(r.get(k) is not True for k in
                ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped SB3 trial required')
    raw=capture.read_bytes(); before=baseline()
    if (old.zero.digest(raw)!=r.get('final_sha256') or raw[0x8000:0x8000+len(data)]!=data or
            raw[:0x8000]!=before[:0x8000] or raw[0x40000:0x7e800]!=before[0x40000:0x7e800] or
            raw[0x7f800:]!=before[0x7f800:]):
        raise ValueError('Stopped SB3 capture / preserved B mismatch')
    return capture,raw


def restore(row,name,path,data):
    expected,before=stopped_receipt(path,data); meta=old.zero.latest_meta(before)
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B entry outside B')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    output=debug(row,[*old.zero.off_gate(),
        *full_compare_commands(TMP/(name+'-before.bin'),expected),'reset halt',
        f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped before B application"}}',
        *off_commands(),*off_report(),
        f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); current=old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or raw[:0x7e800]!=before[:0x7e800] or
            raw[0x7f800:]!=before[0x7f800:] or current[2:5]!=(2,0,0) or
            current[5]<=meta[5] or current[6:10]!=meta[6:10]):
        raise RuntimeError('B restoration / app-private preservation failed')
    row.update(pass_=True,outputs=check_off(output,(0x08040000,)),
        final_capture=str(final),final_sha256=old.zero.digest(raw),final_metadata=list(current),
        final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True,
        b_application_not_run=True)


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--execute-powered',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--full-state-machine',action='store_true',
                   help='One no-load original full FSM, not speed/torque qualification')
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if a.full_state_machine and not a.execute_powered:
        p.error('Full-state-machine mode requires a separate powered execution')
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed:
        p.error('Actual drive OFF, fixed connected no-load motor required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready:
        p.error('Powered no-alarm fixed no-load motor, 0.5A and emergency OFF required')
    data=image(); baseline()
    if not(a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: exact SB3 A BIN/ELF and original B661; no devices'); return 0
    mode='stage' if a.stage_off else ('fsm' if a.full_state_machine else 'speed') if a.execute_powered else 'restore'
    name='sb3-speed-'+mode+'-'+str(time.time_ns()); path=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,
        controller='SB3',voltage_limit_V=1.6,integrator_limit_V=.75,
        torque_accuracy_verified=False,automatic_retry=False,start_attempts=0,
        host_limit_seconds=voltage.cycle.fsm.HOST_MAX_SECONDS if a.full_state_machine else 2.0,
        test_kind='NO_LOAD_STATE_MACHINE_ONLY' if a.full_state_machine else 'NO_LOAD_SPEED',
        tightening_qualified=False,board_lease_us=12000000,motor_connected_fixed=True,
        physical_power_off=bool(a.drive_off_connected_fixed),steps=[],commands=[],uart=[],
        samples=[],postflight={},receipt_path=str(path))
    old.prior.checkpoint(row,'prepared_no_start')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.execute_powered: execute(row,name,a.execute_powered,data,full_fsm=a.full_state_machine)
        else: restore(row,name,a.restore_b_drive_off,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error)); old.prior.checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(path),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
