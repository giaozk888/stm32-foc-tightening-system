"""Pinned output-disabled hand-angle diagnostic, offline unless a mode is explicit.

No motor START, Iq, offset, forced confirmation or direct metadata writes.
Stage OFF, powered preflight, human-paced hand capture, and OFF restoration
are separate operations. The preserved B application is never executed here.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import torque350_five_second_acceptance as previous
import angle_hand_collect as hand
from electrical_angle_report import hand_report

old=previous.old; hw=previous.hw; TMP=previous.TMP
IMAGE=old.ROOT/'foc2_app_a/build/ElectricalAngleHandDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='68ef9fdc565476b5da8af0c511e564874d324c7bf4d6c4200bdd2443d86173bf'
ELF_SHA='2c97a95dcc4d87ff75c58c9f1c91fc83a497bfe94a15a68bf5333c6c20bbba33'
BASE=TMP/'torque350-restore-1792400493770134200-flash.bin'
BASE_SHA='096571836ef2e0fb6a2e969e1c6e04ca6ca40650acd4cdc47a85b7d61cbbf71d'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=223380 or old.zero.digest(data)!=SHA or
            old.zero.digest(ELF.read_bytes())!=ELF_SHA or hw.image_info(data)[0]!='A'):
        raise ValueError('Exact hand-only A BIN/ELF required')
    for marker in (b'ANGLE_HAND_ONLY',b'OK ANGLE BEGIN OUTPUT_OFF=1',
                   b'PP=10 DIR=-1 ZERO=10507',b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE'):
        if marker not in data: raise ValueError('Hand/protection identity missing')
    return data


def baseline():
    raw=BASE.read_bytes(); meta=old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
            meta[2:6]!=(2,0,0,709) or meta[8:10]!=(227964,627317606) or
            zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9]):
        raise ValueError('Exact preserved halted B709 baseline required')
    return raw


def load(path,mode):
    row=json.loads(path.read_text('utf-8'))
    if (path.resolve().parent!=TMP.resolve() or row.get('mode')!=mode or
            row.get('pass_') is not True or row.get('image_sha256')!=SHA or
            row.get('elf_sha256')!=ELF_SHA or row.get('motor_commands')!=0):
        raise ValueError('Exact successful hand-only receipt required')
    return row


def stage(row,name,data):
    if not row['physical_power_off']: raise ValueError('Drive OFF required')
    before=baseline(); dest=TMP/(name+'-staged.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=hw.debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B709"}',
        *hw.full_compare_commands(TMP/(name+'-before.bin'),BASE),
        'reset halt',*hw.off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{dest.as_posix()}}} 0x08000000 0x80000',*hw.off_report(),'halt','shutdown'])
    raw=dest.read_bytes(); old.zero.validate_staged(raw,before,data)
    hw.debug(row,[*old.zero.off_gate(),
        *hw.full_compare_commands(TMP/(name+'-independent.bin'),dest),
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin','halt','shutdown'])
    row.update(pass_=True,staged_capture=str(dest),staged_sha256=old.zero.digest(raw),
        outputs=hw.check_off(output,(0,0x08000000)),metadata=list(old.zero.latest_meta(raw)),
        activation=False,b_boot_private_metadata_unchanged=True,
        independent_readback_pass=True,final_cpu_halted=True,final_outputs_off=True)


def staged_input(path,data):
    r=load(path,'stage'); capture=Path(r['staged_capture']).resolve()
    if (capture.parent!=TMP.resolve() or not r.get('physical_power_off') or
            r.get('independent_readback_pass') is not True): raise ValueError('Verified OFF stage required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=r['staged_sha256']: raise ValueError('Staged capture changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


def capture(row,name,before):
    old.capture_stopped(row,name,before,elf=ELF)
    row.update(final_cpu_halted=True,final_outputs_off=True)


def preflight(row,name,path,data):
    staged,before=staged_input(path,data)
    row.update(stage_receipt=str(path.resolve()),staged_capture=str(staged),staged_sha256=old.zero.digest(before))
    port=old.prior.open_port(); uart=old.prior.JournalConsole(port,row)
    try:
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_intent_no_motion')
        hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(TMP/(name+'-before.bin'),staged),
            'reset halt',*hw.off_commands(),
            *hw.write_mailbox(previous.previous.mailbox(2,2,1,len(data),zlib.crc32(data))),
            'reset run','shutdown'])
        old.prior.wait_health_confirmation(uart,row,hw.fields)
        row['zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        old.prior.wait_timing(uart,row)
        row['ready_state']=hw.fields(uart.query('MOTOR TEST STATUS'))
        if any(row['ready_state'].get(k)!=v for k,v in dict(STATE='1',USED='0',ZERO='3',
                FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0').items()):
            raise RuntimeError('Hand-only READY/off check failed')
        row['final_fw_status']=hw.fields(uart.query('FW STATUS'))
        if any(row['final_fw_status'].get(k)!=v for k,v in dict(CURRENT='A',CONFIRMED='A',
                PENDING='-',ATTEMPTS='0',ACTIVE='0',GEN=row['health_wait']['confirmed_generation']).items()):
            raise RuntimeError('Confirmed generation changed during preflight')
        # Do not BEGIN yet: wait for the human to be ready to turn the shaft.
        row.update(pass_=True,waiting_for_manual_hand=True,final_outputs_off=True)
    finally:
        port.close()
        if not row.get('pass_') and row.get('hardware_attempted'): capture(row,name,before)


def collect(row,name,path,data,seconds):
    ready=load(path,'preflight'); _,before=staged_input(Path(ready['stage_receipt']),data)
    row['preflight_receipt']=str(path.resolve()); row['hand_log']=str(TMP/(name+'.log'))
    port=old.prior.open_port()
    try:
        row['hardware_attempted']=True; old.prior.checkpoint(row,'manual_hand_only_intent')
        with Path(row['hand_log']).open('x',encoding='utf-8') as log:
            uart=hand.HandConsole(port,log)
            fw=hw.fields(uart.query('FW STATUS'))
            # Pin same confirmed generation, not just any A firmware.
            if fw!=ready['final_fw_status']:
                raise RuntimeError('Firmware status changed since preflight')
            print('HAND WINDOW START: slowly turn one full revolution, reverse to start',flush=True)
            row['records']=hand.collect(uart,seconds)
        row['hand_report']=hand_report(Path(row['hand_log']).read_text('utf-8'))
        row['pass_']=row['hand_report']['software_chain_pass']
    finally:
        try:
            # Safety requests only; never motor enable, offset or fault clear.
            uart=old.prior.JournalConsole(port,row)
            row['stop_ack']=uart.query('STOP',.6)
            row['safe_ack']=uart.query('ANALOG SAFE',.6)
        except Exception as error: row['stop_error']=str(error); row['pass_']=False
        port.close()
        if row.get('hardware_attempted'): capture(row,name,before)


def restore(row,name,path,data):
    if not row['physical_power_off']: raise ValueError('Drive OFF required')
    r=json.loads(path.read_text('utf-8')); expected=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or expected.parent!=TMP.resolve() or
            r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            any(r.get(k) is not True for k in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped hand receipt required')
    before=expected.read_bytes(); base=baseline(); meta=old.zero.latest_meta(before)
    if (old.zero.digest(before)!=r['final_sha256'] or meta[2:5]!=(1,0,0) or
            before[0x8000:0x8000+len(data)]!=data or meta[6:8]!=(len(data),zlib.crc32(data)) or
            before[:0x8000]!=base[:0x8000] or before[0x40000:0x7e800]!=base[0x40000:0x7e800] or
            before[0x7f800:]!=base[0x7f800:]): raise ValueError('Stopped identity/preservation mismatch')
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B entry mismatch')
    dest=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'restore_B_intent_no_motion')
    output=hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(TMP/(name+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*hw.write_mailbox(previous.previous.mailbox(3,1,2)),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B application"}}',
        *hw.off_commands(),*hw.off_report(),f'dump_image {{{dest.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=dest.read_bytes(); updated=old.zero.latest_meta(raw)
    if (raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:] or
            updated[2:5]!=(2,0,0) or updated[5]<=meta[5] or updated[6:10]!=meta[6:10]):
        raise RuntimeError('B restoration or byte preservation failed')
    row.update(pass_=True,final_capture=str(dest),final_sha256=old.zero.digest(raw),metadata=list(updated),
        outputs=hw.check_off(output,(0x08040000,)),all_app_private_unchanged=True,
        b_application_not_run=True,final_cpu_halted=True,final_outputs_off=True)


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--preflight-powered',type=Path)
    mode.add_argument('--collect-hand',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off',action='store_true'); p.add_argument('--drive-on-no-alarm',action='store_true')
    p.add_argument('--manual-ready',action='store_true'); p.add_argument('--seconds',type=float,default=30)
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off: p.error('Fresh drive OFF required')
    if a.preflight_powered and not a.drive_on_no_alarm: p.error('Fresh powered/no-alarm state required')
    if a.collect_hand and not a.manual_ready: p.error('Human must be ready to hand turn; no automatic motion')
    if not 5<=a.seconds<=60: p.error('Hand window must be 5..60 seconds')
    data=image(); baseline()
    if not (a.stage_off or a.preflight_powered or a.collect_hand or a.restore_b_drive_off):
        print('OFFLINE PASS: hand-only A and preserved B709; no devices or motor commands'); return 0
    kind='stage' if a.stage_off else 'preflight' if a.preflight_powered else 'hand' if a.collect_hand else 'restore'
    name='angle-hand-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,motor_commands=0,start_attempts=0,automatic_retry=False,
        image_sha256=SHA,elf_sha256=ELF_SHA,physical_power_off=a.drive_off,
        steps=[],commands=[],receipt_path=str(TMP/(name+'.json')))
    old.prior.checkpoint(row,'prepared_no_motion')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.preflight_powered:
            preflight(row,name,a.preflight_powered,data)
        elif a.collect_hand: collect(row,name,a.collect_hand,data,a.seconds)
        else: restore(row,name,a.restore_b_drive_off,data)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'aborted')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+row['receipt_path'],flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
