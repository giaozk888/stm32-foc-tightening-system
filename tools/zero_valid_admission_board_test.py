"""Pinned zero-admission A stage and startup recalibration; NEVER sends START.

Default: files only. Stage requires drive OFF and motor disconnected. Powered
test requires a successful exact stage and a separate power-state assertion.
The normal bootloader health-confirmation reset is observed, not bypassed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import zlib

from firmware_transfer_iap import fields, image_info
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, off_report, check_off
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from pipeline_closed_loop_trial import Console
from health_confirmation_wait import wait_health_confirmation
from tighten_synthetic_swd_recovery import latest_meta

ROOT=Path(__file__).resolve().parents[1]
TMP=ROOT/'tmp'
IMAGE=ROOT/'foc2_app_a/build/ZeroValidAdmissionTrial/foc2.bin'
SHA='11b99efb2323f552b568bb3e8dcbf2f1e0cab5257bd81f15816be2fad475e7e6'
BASE=TMP/'speed-startup-brake-restore-1792302971513816100-flash.bin'
BASE_SHA='97dcb910def29b232878d29eb2f6aa30677a89ebfdda4d63fa9c4750ae5d1d6e'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image():
    data=IMAGE.read_bytes()
    if len(data)!=228428 or digest(data)!=SHA or image_info(data)[0]!='A':
        raise ValueError('Exact offline-tested zero-admission A required')
    for marker in (b'ZERO CAL valid=',b'max_consecutive_reject=',b'SPEED_CTRL=SB1',
                   b'METHOD=TWO_SAMPLE',b'FILTER=NONE OC=RAW_CONFIRM_4'):
        if marker not in data:
            raise ValueError('Zero/protection identity absent')
    return data


def baseline():
    data=BASE.read_bytes()
    if (len(data)!=0x80000 or digest(data)!=BASE_SHA or
            latest_meta(data)[2:6]!=(2,0,0,637)):
        raise ValueError('Exact recovered confirmed B637 required')
    return data


def off_gate():
    return ['init',
        'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Outputs not off"}']


def validate_staged(raw, before, data):
    end=(0x8000+len(data)+0x7ff)&~0x7ff
    if (len(raw)!=0x80000 or raw[:0x8000]!=before[:0x8000] or
            raw[end:]!=before[end:] or raw[0x8000:0x8000+len(data)]!=data or
            raw[0x8000+len(data):end]!=b'\xff'*(end-0x8000-len(data))):
        raise ValueError('Inactive-A verification or outside-slot preservation failed')


def stage(row, name, data):
    before=baseline()
    before_path=TMP/(name+'-before.bin')
    after_path=TMP/(name+'-staged.bin')
    row['hardware_attempted']=True
    debug(row,[*off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected preserved B"}',
        *full_compare_commands(before_path,BASE),'shutdown'])
    row['programming_attempted']=True
    output=debug(row,[*off_gate(),*full_compare_commands(TMP/(name+'-recheck.bin'),before_path),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{after_path.as_posix()}}} 0x08000000 0x80000',
        *off_report(),'halt','shutdown'])
    actual=after_path.read_bytes()
    validate_staged(actual,before,data)
    row.update(staged_capture=str(after_path),staged_sha256=digest(actual),
        metadata=list(latest_meta(actual)),b_and_private_unchanged=True,
        outputs=check_off(output,(0,0x08000000)),activation=False,pass_=True)


def stage_receipt(path, data):
    receipt=json.loads(path.read_text('utf-8'))
    staged=Path(receipt.get('staged_capture','')).resolve()
    if (receipt.get('mode')!='stage' or receipt.get('pass_') is not True or
            receipt.get('image_sha256')!=SHA or staged.parent!=TMP.resolve()):
        raise ValueError('Exact successful zero-admission stage required')
    raw=staged.read_bytes()
    if digest(raw)!=receipt['staged_sha256']:
        raise ValueError('Stage capture changed')
    validate_staged(raw,baseline(),data)
    return staged,raw


def zero_fields(line):
    result=dict(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*)=([^\s]+)',line))
    keys=('valid','reject','total','max_consecutive_reject','zero_u','zero_v',
          'result','STATE','REASON','FLAGS')
    if any(not result.get(k,'').isdigit() for k in keys):
        raise ValueError('Incomplete zero-admission report')
    values={k:int(result[k]) for k in keys}
    if (values['result']!=1 or values['STATE']!=3 or values['REASON'] or values['FLAGS'] or
            values['valid']!=4000 or values['reject']>80 or values['total']>4100 or
            values['max_consecutive_reject']>2 or
            not 0<=values['total']-values['valid']-values['reject']<=4):
        raise ValueError('Zero calibration or bounded admission failed')
    return values


def trial(row,name,path,data):
    staged,raw=stage_receipt(path,data)
    row['stage_receipt']=str(path)
    port=open_port()
    uart=Console(port)  # Read-only whitelist: no START in this orchestrator.
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True
        debug(row,[*off_gate(),*full_compare_commands(TMP/(name+'-pretrial.bin'),staged),
            'reset halt',*off_commands(),*write_mailbox(mailbox),'reset run','shutdown'])
        row['trial_submitted']=True
        wait_health_confirmation(uart,row,fields)
        row['zero']=zero_fields(uart.query('MOTOR TEST ZERO'))
        row['fw']=fields(uart.query('FW STATUS'))
        row['state']=fields(uart.query('MOTOR TEST STATUS'))
        want=dict(STATE='1',USED='0',ZERO='3',FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0')
        if any(row['state'].get(k)!=v for k,v in want.items()):
            raise RuntimeError('READY/output-off precondition lost')
        row['startup_zero_reports']=[zero_fields(line) for line in uart.lines
            if line.startswith('OK ZERO CAL ')]
        if len(row['startup_zero_reports'])<2:
            raise RuntimeError('Need both trial and automatic-confirm-reset calibration reports')
        # Two real calibrations: trial startup, then normal confirmation RESET.
        # Never repeat/reset after a failed calibration to manufacture a PASS.
        row['calibration_runs']=len(row['startup_zero_reports'])
        row['pass_']=True
    finally:
        row['uart']=uart.lines
        port.close()
        if row.get('hardware_attempted'):
            final=TMP/(name+'-final.bin')
            emergency_off(row,final)
            actual=final.read_bytes()
            if actual[:0x7e800]!=raw[:0x7e800] or actual[0x7f800:]!=raw[0x7f800:]:
                raise RuntimeError('Application/private bytes changed during trial')
            row.update(final_capture=str(final),final_sha256=digest(actual),
                all_app_private_unchanged=True,final_metadata=list(latest_meta(actual)))


def restore(row,name,path,data):
    receipt=json.loads(path.read_text('utf-8'))
    expected=Path(receipt.get('final_capture','')).resolve()
    if (receipt.get('mode')!='trial' or receipt.get('pass_') is not True or
            receipt.get('image_sha256')!=SHA or expected.parent!=TMP.resolve() or
            receipt.get('host_start_commands')!=0 or
            any(receipt.get(k) is not True for k in
                ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped successful zero trial required')
    before=expected.read_bytes(); old=baseline(); meta=latest_meta(before)
    if (digest(before)!=receipt['final_sha256'] or meta[2:6]!=(1,0,0,640) or
            before[0x8000:0x8000+len(data)]!=data or
            before[0x40000:0x7e800]!=old[0x40000:0x7e800] or
            before[0x7f800:]!=old[0x7f800:] or
            meta[8:10]!=latest_meta(old)[8:10]):
        raise ValueError('Stopped A/fallback identity mismatch')
    entry=struct.unpack_from('<I',old,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]:
        raise ValueError('B reset entry outside preserved B')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    recovered=TMP/(name+'-flash.bin')
    row['hardware_attempted']=True
    output=debug(row,[*off_gate(),*full_compare_commands(TMP/(name+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped at B entry"}}',
        *off_commands(),*off_report(),
        f'dump_image {{{recovered.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    actual=recovered.read_bytes(); current=latest_meta(actual)
    if (len(actual)!=0x80000 or actual[:0x7e800]!=before[:0x7e800] or
            actual[0x7f800:]!=before[0x7f800:] or current[2:5]!=(2,0,0) or
            current[5]<=meta[5] or current[6:10]!=meta[6:10]):
        raise RuntimeError('B selection or app/private preservation failed')
    row.update(pass_=True,outputs=check_off(output,(0x08040000,)),
        final_metadata=list(current),final_capture=str(recovered),final_sha256=digest(actual),
        all_app_private_unchanged=True,final_cpu_halted=True,final_outputs_off=True,
        b_application_not_run=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--trial-powered',type=Path)
    mode.add_argument('--restore-b-from-trial',type=Path)
    p.add_argument('--drive-12v-off',action='store_true')
    p.add_argument('--drive-12v-on-no-alarm',action='store_true')
    p.add_argument('--motor-disconnected',action='store_true')
    args=p.parse_args()
    if args.stage_off and not(args.drive_12v_off and args.motor_disconnected):
        p.error('Stage requires actual drive OFF and motor U/V/W disconnected')
    if args.trial_powered and not(args.drive_12v_on_no_alarm and args.motor_disconnected):
        p.error('Trial requires actual powered/no-alarm drive and motor disconnected')
    if args.restore_b_from_trial and not args.drive_12v_off:
        p.error('Restoration requires actual drive power OFF')
    data=image()
    if not(args.stage_off or args.trial_powered or args.restore_b_from_trial):
        print('OFFLINE PASS: zero-admission image pinned; no hardware access')
        return 0
    mode='stage' if args.stage_off else ('trial' if args.trial_powered else 'restore')
    name='zero-valid-admission-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,image_sha256=SHA,steps=[],host_start_commands=0,
        automatic_retry=False,direct_metadata_write=False,motor_disconnected=True)
    try:
        if args.stage_off:
            stage(row,name,data)
        elif args.trial_powered:
            trial(row,name,args.trial_powered,data)
        else:
            restore(row,name,args.restore_b_from_trial,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:
                emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup:
                row['cleanup_failure']=str(cleanup)
    path=TMP/(name+'.json')
    path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(('PASS' if row['pass_'] else 'FAIL')+': '+str(path),flush=True)
    if row.get('failure'):
        print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':
    raise SystemExit(main())
