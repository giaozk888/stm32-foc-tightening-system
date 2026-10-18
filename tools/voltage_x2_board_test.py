"""Pinned SB2 1.6V comparison: OFF inactive-A stage, one no-load cycle, restore.

Only the voltage-vector cap differs from SB2. Integral cap remains .75V.
No retries, protection edits, runtime fault clear or SAVE. Default files only.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import sb2_speed_acceptance as sb2
import sb2_fsm_acceptance as cycle
from firmware_transfer_iap import fields, image_info
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, off_report, check_off
from original_closed_loop_trial import emergency_off

TMP=sb2.TMP
IMAGE=sb2.ROOT/'foc2_app_a/build/VoltageX2Trial/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='6f83652e152f569d3830ca2b5d1b9033c475140967b1db34f5bdc5ebed969098'
ELF_SHA='6445cf694132c6c2a9fb95abf6e29f525d989c5f00fc2d95e4ac35780b885f8e'
BASE=TMP/'sb2-fsm-restore-1792312882066619200-flash.bin'
BASE_SHA='07dfb20697687cdb1e5220f87e9b3fa208ec71e233f6849476d482786207be16'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=228532 or sb2.zero.digest(data)!=SHA or image_info(data)[0]!='A' or
            sb2.zero.digest(ELF.read_bytes())!=ELF_SHA):
        raise ValueError('Exact offline-tested 1.6V A BIN/ELF required')
    for marker in (b'SPEED_CTRL=SB2 VLIMIT_MV=1600 ILIMIT_MV=750',
                   b'RPM=20 LEASE_US=12000000',b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4',b'TRIP_MA=4000',b'ZERO CAL valid='):
        if marker not in data: raise ValueError('Voltage/protection marker absent')
    return data


def baseline():
    raw=BASE.read_bytes(); old=cycle.baseline(sb2.image())
    if (len(raw)!=0x80000 or sb2.zero.digest(raw)!=BASE_SHA or
            sb2.zero.latest_meta(raw)[2:6]!=(2,0,0,657) or
            raw[:0x7e800]!=old[:0x7e800] or raw[0x7f800:]!=old[0x7f800:]):
        raise ValueError('Exact original B657 / previous 0.8V A required')
    return raw


def stage(row,name,data):
    before=baseline(); before_path=TMP/(name+'-before.bin')
    row['hardware_attempted']=True
    debug(row,[*sb2.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected preserved halted B657"}',
        *full_compare_commands(before_path,BASE),'shutdown'])
    sb2.prior.checkpoint(row,'baseline_verified')
    staged=TMP/(name+'-staged.bin'); row['programming_attempted']=True
    sb2.prior.checkpoint(row,'inactive_A_program_intent')
    output=debug(row,[*sb2.zero.off_gate(),
        *full_compare_commands(TMP/(name+'-recheck.bin'),before_path),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
        *off_report(),'halt','shutdown'])
    actual=staged.read_bytes(); sb2.zero.validate_staged(actual,before,data)
    row.update(pass_=True,staged_capture=str(staged),staged_sha256=sb2.zero.digest(actual),
        b_and_private_unchanged=True,activation=False,metadata=list(sb2.zero.latest_meta(actual)),
        outputs=check_off(output,(0,0x08000000)),final_cpu_halted=True,final_outputs_off=True)


def stage_receipt(path,data):
    r=json.loads(path.read_text('utf-8')); captured=Path(r.get('staged_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or captured.parent!=TMP.resolve() or
            r.get('mode')!='stage' or r.get('pass_') is not True or
            r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            not r.get('physical_power_off') or not r.get('motor_connected_fixed')):
        raise ValueError('Exact successful 1.6V OFF stage required')
    raw=captured.read_bytes()
    if sb2.zero.digest(raw)!=r.get('staged_sha256'): raise ValueError('Stage capture changed')
    sb2.zero.validate_staged(raw,baseline(),data)
    return captured,raw


def execute(row,name,path,data):
    staged,before=stage_receipt(path,data)
    port=sb2.prior.open_port(); uart=sb2.prior.JournalConsole(port,row)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True; sb2.prior.checkpoint(row,'trial_request_intent')
        debug(row,[*sb2.zero.off_gate(),
            *full_compare_commands(TMP/(name+'-pretrial.bin'),staged),
            'reset halt',*off_commands(),*write_mailbox(mailbox),'reset run','shutdown'])
        row['trial_requests']=1; row['reset_attempts']=1
        sb2.prior.checkpoint(row,'trial_request_submitted')
        sb2.prior.wait_health_confirmation(uart,row,fields)
        row['preflight_zero']=sb2.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        profile=fields(uart.query('MOTOR TEST PROFILE')); cycle.fsm.check_profile(profile,'SB2')
        if profile.get('VLIMIT_MV')!='1600' or profile.get('ILIMIT_MV')!='750':
            raise RuntimeError('Wrong voltage/integrator profile; no START')
        sb2.prior.wait_timing(uart,row); sb2.prior.checkpoint(row,'preflight_pass')
        port.close(); board=cycle.JournalBoard('COM5',row)
        try:
            cycle.fsm.execute(board,row,'A',expected_speed_ctrl='SB2')
            sb2.prior.checkpoint(row,'cycle_completed_outputs_off')
        finally: board.close()
    finally:
        if port.is_open: port.close()
        row['startup_uart']=uart.lines
        if row.get('hardware_attempted'): sb2.capture_stopped(row,name,before,elf=ELF)
    snap=row.get('snapshot')
    if (not snap or snap['first_fault']['valid'] or snap['timing']['deadline_miss'] or
            snap['timing']['actual_late_count']):
        raise RuntimeError('Postflight protection/timing failure')
    row['state_machine_pass']=bool(row.get('cycle_pass')); row['pass_']=row['state_machine_pass']


def stopped_receipt(path,data):
    r=json.loads(path.read_text('utf-8')); captured=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or captured.parent!=TMP.resolve() or
            r.get('mode')!='fsm' or r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            any(r.get(k) is not True for k in
                ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped 1.6V trial required')
    raw=captured.read_bytes(); old=baseline()
    if (sb2.zero.digest(raw)!=r.get('final_sha256') or raw[0x8000:0x8000+len(data)]!=data or
            raw[:0x8000]!=old[:0x8000] or raw[0x40000:0x7e800]!=old[0x40000:0x7e800] or
            raw[0x7f800:]!=old[0x7f800:]):
        raise ValueError('Stopped 1.6V capture/preserved B mismatch')
    return captured,raw


def restore(row,name,path,data):
    expected,before=stopped_receipt(path,data); meta=sb2.zero.latest_meta(before)
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B entry outside B')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    output=debug(row,[*sb2.zero.off_gate(),
        *full_compare_commands(TMP/(name+'-before.bin'),expected),'reset halt',
        f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped before B application"}}',
        *off_commands(),*off_report(),
        f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); current=sb2.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or raw[:0x7e800]!=before[:0x7e800] or
            raw[0x7f800:]!=before[0x7f800:] or current[2:5]!=(2,0,0) or
            current[5]<=meta[5] or current[6:10]!=meta[6:10]):
        raise RuntimeError('B restore or app/private preservation failed')
    row.update(pass_=True,outputs=check_off(output,(0x08040000,)),
        final_capture=str(final),final_sha256=sb2.zero.digest(raw),final_metadata=list(current),
        final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True,
        b_application_not_run=True)


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--execute-powered',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed:
        p.error('Actual 12V OFF, connected/fixed no-load motor required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready:
        p.error('Powered no-alarm fixed no-load motor, 0.5A and emergency OFF required')
    data=image(); baseline()
    if not(a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: exact 1.6V candidate and preserved B657; no devices'); return 0
    mode='stage' if a.stage_off else 'fsm' if a.execute_powered else 'restore'
    name='voltage-x2-'+mode+'-'+str(time.time_ns()); path=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,
        voltage_limit_V=1.6,integrator_limit_V=.75,test_kind='NO_LOAD_STATE_MACHINE_ONLY',
        tightening_qualified=False,torque_accuracy_verified=False,automatic_retry=False,
        start_attempts=0,host_limit_seconds=cycle.fsm.HOST_MAX_SECONDS,board_lease_us=12000000,
        motor_connected_fixed=True,physical_power_off=bool(a.drive_off_connected_fixed),
        steps=[],commands=[],uart=[],samples=[],postflight={},receipt_path=str(path))
    sb2.prior.checkpoint(row,'prepared_no_start')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.execute_powered: execute(row,name,a.execute_powered,data)
        else: restore(row,name,a.restore_b_drive_off,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error)); sb2.prior.checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    sb2.prior.checkpoint(row,'complete' if row['pass_'] else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(path),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
