"""Pinned 200mA direct-limit original-FSM trial at 20rpm, no retry.

Default files only. Stage OFF inactive A; execute needs a fresh ON assertion;
restore OFF through the existing bootloader mailbox, stop before B app runs.
Guard admission and real speed tracking are separately reported. No fault
clear, SAVE, phase/sign/gain/threshold change or alternate START path.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import time
import zlib
import sb3_speed_acceptance as previous
import torque_chain_200ma_acceptance as torque_previous
import rundown_startup_decode as startup
from foc_path_profile_report import symbols
from firmware_transfer_iap import fields,image_info
from latest_original_fsm_stage import full_compare_commands,off_commands,write_mailbox
from original_closed_loop_updated_stage import debug,off_report,check_off
from original_closed_loop_trial import emergency_off
from loaded_fsm_motion import RecordedBoard,check_profile

old=previous.old; TMP=old.TMP
IMAGE=old.ROOT/'foc2_app_a/build/Rundown200mADirectLimitTrial/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='a4848c2e68723a04931ed395bc0a0bf177abf3648db52d484f69756eddf5e96a'
ELF_SHA='73866c260a7d7117050a94759b583c7034ee473fec42df90369564f7e54f8146'
BASE=TMP/'torque200-limit-restore-1792383506468509200-flash.bin'
BASE_SHA='bd6f4bde2038b7376585e79ae3f03b0dbcfbeee5d750969847a5fb586bc86268'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=228220 or old.zero.digest(data)!=SHA or image_info(data)[0]!='A' or
            old.zero.digest(ELF.read_bytes())!=ELF_SHA):
        raise ValueError('Exact offline-tested rundown A BIN/ELF required')
    for marker in (b'SPEED_CTRL=SB3 VLIMIT_MV=1600 ILIMIT_MV=750',b'NO_ROTATION',
                   b'SCHEMA=2 BINARY_ONLY=1',b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000'):
        if marker not in data: raise ValueError('Rundown/protection/schema identity absent')
    if symbols(ELF)['cl_startup'][1]!=startup.TRACE_SIZE:
        raise ValueError('Wrong startup schema')
    return data


def baseline():
    raw=BASE.read_bytes(); before=torque_previous.baseline(); prior=torque_previous.image()
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
            old.zero.latest_meta(raw)[2:6]!=(2,0,0,689) or
            raw[0x8000:0x8000+len(prior)]!=prior or raw[:0x8000]!=before[:0x8000] or
            raw[0x40000:0x7e800]!=before[0x40000:0x7e800] or raw[0x7f800:]!=before[0x7f800:]):
        raise ValueError('Exact preserved halted B689 baseline required')
    return raw


def stage(row,name,data):
    before=baseline(); saved=TMP/(name+'-before.bin'); row['hardware_attempted']=True
    debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected preserved halted B689"}',
        *full_compare_commands(saved,BASE),'shutdown'])
    old.prior.checkpoint(row,'baseline_verified')
    staged=TMP/(name+'-staged.bin'); row['programming_attempted']=True
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=debug(row,[*old.zero.off_gate(),*full_compare_commands(TMP/(name+'-recheck.bin'),saved),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',*off_report(),'halt','shutdown'])
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
        raise ValueError('Exact successful OFF rundown stage required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=r.get('staged_sha256'): raise ValueError('Stage capture changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


def classify(row,ram):
    table=symbols(ELF)
    def word(name):
        address,size=table[name]; offset=address-0x20000000
        if size not in (1,2,4) or offset<0 or offset+size>len(ram):
            raise ValueError('Scalar layout mismatch: '+name)
        return int.from_bytes(ram[offset:offset+size],'little')
    address,size=table['cl_startup']; offset=address-0x20000000
    if size!=startup.TRACE_SIZE or offset<0 or offset+size>len(ram):
        raise ValueError('Startup capture layout mismatch')
    trace=startup.decode(ram[offset:offset+size]); trace['capture_identity_verified']=True
    guard_addr,guard_size=table['tightening_rundown']
    if guard_size!=20: raise ValueError('Rundown guard layout mismatch')
    guard=struct.unpack_from('<3If3Bx',ram,guard_addr-0x20000000)
    row['startup_diagnostic']=trace
    row['rundown_guard']=dict(last_ms=guard[0],motion_ms=guard[1],drive_ms=guard[2],
        motion_position_deg=guard[3],armed=guard[4],motion_candidate=guard[5],drive_candidate=guard[6])
    terminal=dict(outcome=word('tightening_last_outcome'),contact=word('tightening_contact_confirmed'),
        stage=word('tightening_test_stage'),core_fault=word('foc_fault'))
    row['guard_terminal']=terminal
    rows=trace['rows']+([trace['terminal']] if trace['terminal'] else [])
    illegal=any(2<=r['state']<=7 and not r['rundown_armed'] for r in rows)
    no_rotation=terminal==dict(outcome=7,contact=0,stage=11,core_fault=0) and not guard[4]
    reason=row['snapshot']['first_fault']
    expected_process_fault=(no_rotation and reason['valid']==1 and reason['domain']==3 and reason['fault_reason']==7)
    timing=row['snapshot']['timing']
    timing_ok=(0<timing['wall_max_us']<50 and not timing['deadline_miss'] and
               not timing['actual_late_count'] and timing['actual_margin_min_us']>1)
    fault_ok=not reason['valid'] or expected_process_fault
    safe=row.get('safe',{})
    cleanup_ok=(row.get('recipe_restored') is True and all(safe.get(k)==v for k,v in
        dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()) and not row.get('stop_error'))
    full=row.get('full_state_machine',False)
    full_pass=bool(full and row.get('cycle_pass') and guard[4] and
        terminal==dict(outcome=1,contact=1,stage=9,core_fault=0))
    speed_pass=bool(row.get('motion_pass'))
    if full:
        # Provisional observed SPEED tracking, not independent tachometer or
        # torque qualification. Never infer it from a terminal COMPLETE OK.
        near_start=None; longest=0.0; previous_at=None; speeds=[]
        for sample in row.get('samples',[]):
            s=sample['status']; at=sample['elapsed_s']
            if s.get('STAGE')!='1': continue
            try: rpm=float(s['CTRL'].removesuffix('rpm'))
            except (ValueError,KeyError): rpm=float('nan')
            if math.isfinite(rpm): speeds.append(rpm)
            if (math.isfinite(rpm) and abs(rpm-20)<=5 and
                    (previous_at is None or at-previous_at<=.15)):
                if near_start is None: near_start=at
                longest=max(longest,at-near_start)
            else: near_start=None
            previous_at=at
        speed_pass=longest>=.25
        row['full_speed_observation']=dict(target_rpm=20,provisional_band_rpm=5,
            required_observed_seconds=.25,longest_in_band_seconds=longest,
            peak_ctrl_rpm=max(speeds) if speeds else None,independent_tachometer_verified=False)
    row.update(no_rotation_protection_verified=bool(no_rotation and expected_process_fault and not illegal),
        guard_pass=bool(not illegal and (expected_process_fault or
            full_pass or (not full and row.get('motion_pass') and guard[4] and not terminal['contact']))),
        full_state_machine_pass=full_pass,
        timing_pass=timing_ok,speed_tracking_pass=bool(speed_pass and
            not row.get('motion_failure') and cleanup_ok),host_cleanup_pass=cleanup_ok,
        unexpected_fault=not fault_ok)
    row['pass_']=bool(row['guard_pass'] and row['speed_tracking_pass'] and timing_ok and fault_ok)


def motion(board,row,full_fsm=False):
    if full_fsm:
        previous.voltage.cycle.fsm.execute(board,row,'A',expected_speed_ctrl='SB3')
    else: old.prior.motion(board,row,expected_speed_ctrl='SB3')


def resume_receipt(path,data):
    raise ValueError('No pre-START resume in this one-shot revision; require new OFF stage')


def execute(row,name,path,data,full_fsm=False,resume=False):
    staged,before=(resume_receipt if resume else stage_receipt)(path,data)
    port=old.prior.open_port(); uart=old.prior.JournalConsole(port,row)
    try:
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_request_intent')
        request=[]
        if not resume:
            body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
            mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
            request=write_mailbox(mailbox)
        debug(row,[*old.zero.off_gate(),*full_compare_commands(TMP/(name+'-pretrial.bin'),staged),
            'reset halt',*off_commands(),*request,'reset run','shutdown'])
        row['trial_requests']=0 if resume else 1
        row['reset_attempts']=1
        old.prior.checkpoint(row,'trial_request_submitted')
        old.prior.wait_health_confirmation(uart,row,fields)
        row['preflight_zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        profile=fields(uart.query('MOTOR TEST PROFILE')); check_profile(profile,'SB3')
        # Exact BIN/ELF + full Flash readback already bind schema=2. Do not
        # send a command outside the shared read-only startup allowlist.
        if profile.get('VLIMIT_MV')!='1600':
            raise RuntimeError('Wrong rundown schema/profile; no START')
        old.prior.wait_timing(uart,row); old.prior.checkpoint(row,'preflight_pass')
        port.close()
        board=(previous.voltage.cycle.JournalBoard if full_fsm else RecordedBoard)('COM5',row)
        try:
            try: motion(board,row,full_fsm)
            except Exception as error:
                row['motion_failure']=str(error)  # Expected NO_ROTATION is classified from RAM, never retried.
        finally: board.close()
    finally:
        if port.is_open: port.close()
        row['startup_uart']=uart.lines
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    if not row.get('snapshot'): raise RuntimeError('No matching new A snapshot; no acceptance')
    classify(row,Path(row['ram_capture']).read_bytes())


def restore(row,name,path,data):
    r=json.loads(path.read_text('utf-8')); expected=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or expected.parent!=TMP.resolve() or
            r.get('mode')!='run' or r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            any(r.get(k) is not True for k in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped rundown receipt required')
    before=expected.read_bytes(); original=baseline(); meta=old.zero.latest_meta(before)
    if (old.zero.digest(before)!=r.get('final_sha256') or before[0x8000:0x8000+len(data)]!=data or
            before[:0x8000]!=original[:0x8000] or before[0x40000:0x7e800]!=original[0x40000:0x7e800] or
            before[0x7f800:]!=original[0x7f800:]): raise ValueError('Stopped identity/preserved B mismatch')
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B entry mismatch')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    output=debug(row,[*old.zero.off_gate(),*full_compare_commands(TMP/(name+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B app"}}',
        *off_commands(),*off_report(),f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); current=old.zero.latest_meta(raw)
    if (raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:] or
            current[2:5]!=(2,0,0) or current[5]<=meta[5] or current[6:10]!=meta[6:10]):
        raise RuntimeError('B restore/app-private preservation failed')
    row.update(pass_=True,outputs=check_off(output,(0x08040000,)),
        final_capture=str(final),final_sha256=old.zero.digest(raw),metadata=list(current),
        final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True,b_application_not_run=True)


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--execute-powered',type=Path); mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    p.add_argument('--full-state-machine',action='store_true')
    a=p.parse_args()
    powered=a.execute_powered
    if powered and not a.full_state_machine:
        p.error('This revision permits only a single full original FSM test')
    if a.full_state_machine and not powered:
        p.error('Full state-machine mode requires separate powered execution')
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed:
        p.error('Fresh drive OFF and fixed connected motor required')
    if powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready:
        p.error('Fresh powered/no-alarm 0.5A fixed motor and emergency OFF required')
    data=image(); baseline()
    if not (a.stage_off or powered or a.restore_b_drive_off):
        print('OFFLINE PASS: pinned rundown A and halted B689; no devices'); return 0
    mode='stage' if a.stage_off else 'run' if powered else 'restore'
    name='rundown200-'+mode+'-'+str(time.time_ns()); receipt=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,start_attempts=0,
        automatic_retry=False,motor_connected_fixed=True,physical_power_off=a.drive_off_connected_fixed,
        full_state_machine=a.full_state_machine,
        host_limit_seconds=previous.voltage.cycle.fsm.HOST_MAX_SECONDS if a.full_state_machine else 2.0,
        board_lease_us=12000000,torque_accuracy_verified=False,
        steps=[],commands=[],uart=[],samples=[],postflight={},receipt_path=str(receipt))
    old.prior.checkpoint(row,'prepared_no_start')
    try:
        if a.stage_off: stage(row,name,data)
        elif powered: execute(row,name,powered,data,full_fsm=a.full_state_machine,
                             resume=False)
        else: restore(row,name,a.restore_b_drive_off,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error)); old.prior.checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(receipt),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
