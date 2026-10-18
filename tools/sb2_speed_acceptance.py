"""Pinned SB2 stage, one no-load 20 rpm/2s trial, or drive-OFF B restore.

Default is files only. No retries, protection edits, SAVE or full tightening.
The 2s STOP is host-timed; the existing independent 12s board lease is unchanged.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import sb1_speed_acceptance as prior
import zero_valid_admission_board_test as zero
from firmware_transfer_iap import fields, image_info
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, off_report, check_off
from original_closed_loop_trial import emergency_off
from loaded_fsm_motion import RecordedBoard, check_profile
from loaded_fsm_snapshot_report import decode

ROOT=zero.ROOT; TMP=zero.TMP
IMAGE=ROOT/'foc2_app_a/build/SpeedBumplessTrial/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='b78864f64ff417d4cfc3101f9d6f22292a96e89807359f4154aa8ee6ba0f8488'
ELF_SHA='e214429a993cd852affdf5a3d849c35a51740c79fe108b601a5bb3c8ad314110'
BASE=TMP/'sb1-speed-interrupted-restore-1792310314390233000-flash.bin'
BASE_SHA='127e413794f5b0b1e731295c630a97347662e2c91669584d21c2d2f09e7bf164'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=228500 or zero.digest(data)!=SHA or image_info(data)[0]!='A'
            or zero.digest(ELF.read_bytes())!=ELF_SHA):
        raise ValueError('Exact offline-tested SB2 A BIN/ELF required')
    for marker in (b'SPEED_CTRL=SB2',b'RPM=20 LEASE_US=12000000',
                   b'METHOD=TWO_SAMPLE',b'FILTER=NONE OC=RAW_CONFIRM_4',
                   b'ZERO CAL valid='):
        if marker not in data: raise ValueError('SB2/protection identity absent')
    return data


def baseline():
    raw=BASE.read_bytes()
    if (len(raw)!=0x80000 or zero.digest(raw)!=BASE_SHA or
            zero.latest_meta(raw)[2:6]!=(2,0,0,649)):
        raise ValueError('Exact preserved B649 baseline required')
    return raw


def stage(row,name,data):
    before=baseline(); before_path=TMP/(name+'-before.bin')
    row['hardware_attempted']=True
    debug(row,[*zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected preserved halted B"}',
        *full_compare_commands(before_path,BASE),'shutdown'])
    prior.checkpoint(row,'baseline_verified')
    staged=TMP/(name+'-staged.bin')
    row['programming_attempted']=True
    prior.checkpoint(row,'inactive_A_program_intent')
    output=debug(row,[*zero.off_gate(),
        *full_compare_commands(TMP/(name+'-recheck.bin'),before_path),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
        *off_report(),'halt','shutdown'])
    raw=staged.read_bytes(); zero.validate_staged(raw,before,data)
    row.update(pass_=True,staged_capture=str(staged),staged_sha256=zero.digest(raw),
        metadata=list(zero.latest_meta(raw)),b_and_private_unchanged=True,
        outputs=check_off(output,(0,0x08000000)),activation=False,
        final_cpu_halted=True,final_outputs_off=True)


def stage_receipt(path,data):
    receipt=json.loads(path.read_text('utf-8'))
    capture=Path(receipt.get('staged_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            receipt.get('mode')!='stage' or receipt.get('pass_') is not True or
            receipt.get('image_sha256')!=SHA or receipt.get('elf_sha256')!=ELF_SHA or
            not receipt.get('physical_power_off') or not receipt.get('motor_connected_fixed')):
        raise ValueError('Exact successful SB2 OFF stage required')
    raw=capture.read_bytes()
    if zero.digest(raw)!=receipt.get('staged_sha256'):
        raise ValueError('Staged capture changed')
    zero.validate_staged(raw,baseline(),data)
    return capture,raw


def capture_stopped(row,name,before,elf=ELF):
    flash=TMP/(name+'-flash.bin'); ram=TMP/(name+'-ram.bin')
    emergency_off(row,flash)
    prior.checkpoint(row,'halted_outputs_off')
    output=debug(row,['init','halt',*zero.off_gate()[1:],*off_report(),
        f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000','shutdown'])
    raw=flash.read_bytes()
    row['outputs']=check_off(output,(0x08008000,0x08040000,0,0x08000000))
    if raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:]:
        raise RuntimeError('Application/private bytes changed during trial')
    row.update(final_capture=str(flash),final_sha256=zero.digest(raw),
        final_metadata=list(zero.latest_meta(raw)),all_app_private_unchanged=True,
        ram_capture=str(ram))
    # Only interpret A RAM with its ELF, never bootloader/fallback RAM.
    if row['outputs']['VTOR']==0x08008000:
        row['snapshot']=decode(ram.read_bytes(),elf)
    prior.checkpoint(row,'snapshot_saved')


def execute(row,name,path,data):
    staged,before=stage_receipt(path,data)
    port=prior.open_port(); uart=prior.JournalConsole(port,row)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True
        prior.checkpoint(row,'trial_request_intent')
        debug(row,[*zero.off_gate(),
            *full_compare_commands(TMP/(name+'-pretrial.bin'),staged),
            'reset halt',*off_commands(),*write_mailbox(mailbox),'reset run','shutdown'])
        row['trial_requests']=1; row['reset_attempts']=1
        prior.checkpoint(row,'trial_request_submitted')
        prior.wait_health_confirmation(uart,row,fields)
        row['preflight_zero']=zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        check_profile(fields(uart.query('MOTOR TEST PROFILE')),'SB2')
        prior.wait_timing(uart,row)
        prior.checkpoint(row,'preflight_pass')
        port.close()
        board=RecordedBoard('COM5',row)
        try: prior.motion(board,row,expected_speed_ctrl='SB2')
        finally: board.close()
    finally:
        if port.is_open: port.close()
        row['startup_uart']=uart.lines
        if row.get('hardware_attempted'): capture_stopped(row,name,before)
    snap=row.get('snapshot')
    if (not snap or snap['first_fault']['valid'] or snap['timing']['deadline_miss'] or
            snap['timing']['actual_late_count']):
        raise RuntimeError('Postflight snapshot/protection/timing failure')
    row['pass_']=bool(row.get('motion_pass'))


def stopped_receipt(path,data):
    receipt=json.loads(path.read_text('utf-8'))
    capture=Path(receipt.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            receipt.get('mode') not in ('speed','fsm') or receipt.get('image_sha256')!=SHA or
            receipt.get('elf_sha256')!=ELF_SHA or
            any(receipt.get(k) is not True for k in
                ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped SB2 trial required')
    raw=capture.read_bytes(); old=baseline()
    if (zero.digest(raw)!=receipt.get('final_sha256') or
            raw[0x8000:0x8000+len(data)]!=data or raw[:0x8000]!=old[:0x8000] or
            raw[0x40000:0x7e800]!=old[0x40000:0x7e800] or raw[0x7f800:]!=old[0x7f800:]):
        raise ValueError('Stopped capture or preserved B mismatch')
    return capture,raw


def restore(row,name,path,data):
    expected,before=stopped_receipt(path,data); meta=zero.latest_meta(before)
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]:
        raise ValueError('B entry outside preserved B')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    output=debug(row,[*zero.off_gate(),
        *full_compare_commands(TMP/(name+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped before B application"}}',
        *off_commands(),*off_report(),
        f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); current=zero.latest_meta(raw)
    if (len(raw)!=0x80000 or raw[:0x7e800]!=before[:0x7e800] or
            raw[0x7f800:]!=before[0x7f800:] or current[2:5]!=(2,0,0) or
            current[5]<=meta[5] or current[6:10]!=meta[6:10]):
        raise RuntimeError('B selection or app/private preservation failed')
    row.update(pass_=True,outputs=check_off(output,(0x08040000,)),
        final_capture=str(final),final_sha256=zero.digest(raw),final_metadata=list(current),
        all_app_private_unchanged=True,final_cpu_halted=True,final_outputs_off=True,
        b_application_not_run=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--execute-powered',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed:
        p.error('Actual drive OFF, connected/fixed no-load motor required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready:
        p.error('Actual powered/no-alarm fixed no-load motor, 0.5A and emergency OFF required')
    data=image(); baseline()
    if not(a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: pinned SB2 A BIN/ELF and B649; no device access'); return 0
    mode='stage' if a.stage_off else 'speed' if a.execute_powered else 'restore'
    name='sb2-speed-'+mode+'-'+str(time.time_ns()); path=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,steps=[],
        commands=[],uart=[],samples=[],postflight={},automatic_retry=False,
        start_attempts=0,host_limit_seconds=2.0,motor_connected_fixed=True,
        physical_power_off=bool(a.drive_off_connected_fixed),receipt_path=str(path))
    prior.checkpoint(row,'prepared_no_start')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.execute_powered: execute(row,name,a.execute_powered,data)
        else: restore(row,name,a.restore_b_drive_off,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error))
        prior.checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    prior.checkpoint(row,'complete' if row['pass_'] else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(path),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
