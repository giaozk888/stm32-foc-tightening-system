"""Pinned PWM-boundary trace A: separate OFF staging and ON read-only trial.

Offline by default. Never sends START, bridge-enable, clear-fault, forced
confirmation, or an automatic second trial. Full Flash backups stay private.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

import rc_optimized_board_test as prior
import rc_protected_trial as protected
from firmware_transfer_iap import image_info, fields
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from tighten_synthetic_swd_recovery import latest_meta

ROOT, OUTPUT, PRIVATE = prior.ROOT, prior.OUTPUT, prior.PRIVATE
PRIOR = OUTPUT / 'rc-optimized-trial-1792126877053386600.json'
FAILED_TRIAL = OUTPUT / 'rc-boundary-trial-1792128741578925600.json'
BASE_SHA = 'f941ca8efb40910b92d56063597c8d3c2bb19ea106a2b82309bfec7fbc5e27b9'
BASE_META = (1112493908,3,2,0,0,570,208236,1538858691,210916,453748590,0,1703675023)
IMAGE = ROOT / 'foc2_app_a/build/RcBoundaryAttribution/foc2.bin'
SHA = '059cea4b5aad85d774fd41af9ac86440d57f82b22afee7861c3f1355beea3643'
SIZE = 213580


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_path(value):
    path = Path(value).resolve()
    if path.parent != PRIVATE.resolve():
        raise ValueError('Full capture must remain in the private evidence directory')
    return path


def image():
    data = IMAGE.read_bytes()
    if len(data) != SIZE or digest(data) != SHA or image_info(data)[0] != 'A':
        raise ValueError('Exact offline-tested boundary A image required')
    for marker in (b'NAME=RC_BOUNDARY_TRACE HARD_OFF=0 ADMISSION=0',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'ADC BOUNDARY FRAME', b'ADC BOUNDARY IRQ', b'HW_VERIFIED=0'):
        if marker not in data:
            raise ValueError('Missing trace or protected profile marker')
    return data


def baseline():
    row = json.loads(PRIOR.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('normally_confirmed') is not True or
            row.get('final_sha256') != BASE_SHA or row.get('image_sha256') != prior.SHA or
            tuple(row.get('final_metadata', ())) != BASE_META or
            (row.get('host_motor_commands'), row.get('host_uart_trial_commits')) != (0,0) or
            any(row.get(k) is not True for k in ('final_outputs_off','final_cpu_halted',
                                               'all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact stopped, normally confirmed B570 receipt required')
    path = private_path(row['final_backup'])
    raw = path.read_bytes()
    if (len(raw) != 0x80000 or digest(raw) != BASE_SHA or latest_meta(raw) != BASE_META or
            digest(raw[0x40000:0x40000+prior.SIZE]) != prior.SHA):
        raise ValueError('B570 full capture changed')
    return path,raw


def off_gate(vtor):
    return ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not already halted"}',
            f'if {{[mrw 0xE000ED08] != {vtor:#x}}} {{error "Unexpected VTOR"}}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Outputs not off"}']


def compare_stage(before, actual, data):
    if len(actual) != 0x80000 or actual[0x8000:0x8000+SIZE] != data:
        raise ValueError('Inactive A image/full capture mismatch')
    end = 0x8000+SIZE
    erased_end = (end+0x7ff)&~0x7ff
    if actual[end:erased_end] != b'\xff'*(erased_end-end):
        raise ValueError('Unexpected last A erase-page tail')
    if actual[:0x8000] != before[:0x8000] or actual[erased_end:] != before[erased_end:]:
        raise ValueError('Flash outside inactive A erase pages changed')
    if latest_meta(actual) != BASE_META:
        raise ValueError('Staging changed metadata')


def stage_commands(live, expected, staged):
    return [*off_gate(0x08040000), *full_compare_commands(live,expected),
            'reset halt',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
            *off_commands(),
            f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
            f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
            f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
            *off_report(), 'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
            'halt','shutdown']


def stage(row, run, data):
    expected,before = baseline()
    row['hardware_attempted'] = True
    inspection = PRIVATE/(run+'-inspection.bin')
    output = debug(row,[*off_gate(0x08040000),*off_report(),
                        f'dump_image {{{inspection.as_posix()}}} 0x08000000 0x80000','shutdown'])
    row['inspection_outputs'] = check_off(output,(0x08040000,))
    if inspection.read_bytes() != before:
        raise ValueError('Live full Flash differs from last stopped B570 capture')
    row['inspection_pass'] = True
    print('INSPECT PASS: exact confirmed B570; full backup and outputs off',flush=True)
    staged = PRIVATE/(run+'-staged.bin')
    row['programming_attempted'] = True
    output = debug(row,stage_commands(PRIVATE/(run+'-prewrite.bin'),expected,staged))
    row['staged_outputs'] = check_off(output,(0,0x08000000))
    actual=staged.read_bytes()
    compare_stage(before,actual,data)
    row.update(pass_=True,staged_backup=str(staged),staged_sha256=digest(actual),
               final_metadata=list(latest_meta(actual)),all_bytes_outside_a_pages_unchanged=True,
               final_outputs_off=True,final_cpu_halted=True,activation=False)
    print('STAGE PASS: trace A exact; confirmed B and private data retained; not activated',flush=True)


def load_stage(receipt, data):
    receipt=Path(receipt).resolve()
    if receipt.parent != OUTPUT.resolve() or not receipt.name.startswith('rc-boundary-stage-'):
        raise ValueError('Expected exact boundary stage receipt')
    row=json.loads(receipt.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage' or
            row.get('image_sha256') != SHA or row.get('activation') is not False or
            tuple(row.get('final_metadata',())) != BASE_META or
            any(row.get(k) is not True for k in ('inspection_pass',
               'all_bytes_outside_a_pages_unchanged','final_outputs_off','final_cpu_halted'))):
        raise ValueError('Unactivated exact trace A stage required')
    path=private_path(row['staged_backup'])
    raw=path.read_bytes()
    _,before=baseline()
    if digest(raw) != row.get('staged_sha256'):
        raise ValueError('Staged capture hash changed')
    compare_stage(before,raw,data)
    return path,raw


def mailbox(data):
    if len(data) != SIZE or digest(data) != SHA:
        raise ValueError('Exact trace A only')
    body=struct.pack('<7I',0x584f424d,1,2,2,1,SIZE,zlib.crc32(data))
    return struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))


def restore_mailbox():
    # The trial A is rejected; select only the already-confirmed B570.
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    return struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))


def load_failed_trial(data):
    receipt=json.loads(FAILED_TRIAL.read_text('utf-8'))
    if (receipt.get('pass_') is not False or receipt.get('mode')!='trial' or
            receipt.get('failure')!='Trace A startup fault; no retry' or
            receipt.get('image_sha256')!=SHA or receipt.get('host_motor_commands')!=0 or
            receipt.get('host_uart_trial_commits')!=0 or
            receipt.get('last_state',{}).get('FLAGS')!='256' or
            any(receipt.get(k) is not True for k in ('final_outputs_off',
                'final_cpu_halted','all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact halted failed A trace receipt required')
    path=private_path(receipt['final_backup'])
    raw=path.read_bytes()
    _,staged=load_stage(OUTPUT/'rc-boundary-stage-1792128534815748900.json',data)
    if digest(raw)!=receipt.get('final_sha256') or raw[:0x7e800]!=staged[:0x7e800] or raw[0x7f800:]!=staged[0x7f800:]:
        raise ValueError('Failed A full capture mismatch')
    meta=latest_meta(raw)
    if (tuple(receipt.get('final_metadata',()))!=meta or meta[2:5]!=(2,1,1) or
            meta[5]<=BASE_META[5] or meta[6:8]!=(SIZE,zlib.crc32(data)) or
            meta[8:10]!=BASE_META[8:10]):
        raise ValueError('Unexpected failed A metadata')
    return path,raw


def restore_commands(live,expected,recovered,entry):
    if not 0x08040000<=entry<0x0807e800 or entry&1:
        raise ValueError('B reset entry outside application slot')
    return [*off_gate(0x08008000),*full_compare_commands(live,expected),
            'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(restore_mailbox()),
            'reset run','wait_halt 25000',f'rbp {entry:#x}',
            f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped before B instructions"}}',
            *off_commands(),*off_report(),
            'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
            f'dump_image {{{recovered.as_posix()}}} 0x08000000 0x80000','halt','shutdown']


def restore(row,run,data):
    expected,before=load_failed_trial(data)
    _,base=baseline()
    entry=struct.unpack_from('<I',base,0x40004)[0]&~1
    row['hardware_attempted']=True
    inspection=PRIVATE/(run+'-inspection.bin')
    output=debug(row,[*off_gate(0x08008000),*off_report(),
                      f'dump_image {{{inspection.as_posix()}}} 0x08000000 0x80000','shutdown'])
    row['inspection_outputs']=check_off(output,(0x08008000,))
    if inspection.read_bytes()!=before:
        raise ValueError('Live Flash differs from halted failed A receipt')
    row['inspection_pass']=True
    recovered=PRIVATE/(run+'-recovered.bin')
    row['restore_attempted']=True
    output=debug(row,restore_commands(PRIVATE/(run+'-before.bin'),expected,recovered,entry))
    row['recovered_outputs']=check_off(output,(0x08040000,))
    actual=recovered.read_bytes()
    if len(actual)!=len(before) or actual[:0x7e800]!=before[:0x7e800] or actual[0x7f800:]!=before[0x7f800:]:
        raise RuntimeError('Restore changed application or private Flash bytes')
    meta=latest_meta(actual)
    if (meta[2:5]!=(2,0,0) or meta[5]<=latest_meta(before)[5] or
            meta[6:10]!=latest_meta(before)[6:10]):
        raise RuntimeError('Normal confirmed-B restore metadata missing')
    row.update(pass_=True,recovered_backup=str(recovered),final_sha256=digest(actual),
               final_metadata=list(meta),all_app_and_private_bytes_unchanged=True,
               final_outputs_off=True,final_cpu_halted=True,motor_commands=0)
    print('RESTORE PASS: previously confirmed B selected and halted before app instructions',flush=True)


class Console(protected.Console):
    READ=protected.Console.READ | frozenset((
        'ENC DIAG',
        'ADC BOUNDARY','ADC BOUNDARY FIRST','ADC BOUNDARY FIRST IRQ',
        'ADC BOUNDARY WORST','ADC BOUNDARY WORST IRQ'))


def sample(uart):
    result=dict(host_time=time.monotonic())
    for key,command in (('fw','FW STATUS'),('profile','MOTOR TEST PROFILE'),
            ('state','MOTOR TEST STATUS'),('zero','MOTOR TEST ZERO'),
            ('timing','MOTOR TEST TIMING'),('adc','ADC TIMING'),
            ('commit','ADC COMMIT'),('protection','MOTOR TEST PROTECTION'),
            ('fault','MOTOR TEST FAULT'),('encoder','ENC DIAG'),
            ('boundary','ADC BOUNDARY'),('first','ADC BOUNDARY FIRST'),
            ('first_irq','ADC BOUNDARY FIRST IRQ'),
            ('worst','ADC BOUNDARY WORST'),('worst_irq','ADC BOUNDARY WORST IRQ')):
        result[key]=fields(uart.query(command))
    return result


def trial_commands(live,expected,data):
    return [*off_gate(0),*full_compare_commands(live,expected),'reset halt',
            *write_mailbox(mailbox(data)),'reset run','shutdown']


def compare_final(before, actual, data, normally_confirmed, activation_submitted):
    if len(actual)!=0x80000 or actual[:0x7e800]!=before[:0x7e800] or actual[0x7f800:]!=before[0x7f800:]:
        raise RuntimeError('Trial changed application or private Flash bytes')
    meta=latest_meta(actual)
    if not activation_submitted:
        if meta!=BASE_META:
            raise RuntimeError('Unsubmitted trial changed boot metadata')
    elif (meta[5]<=BASE_META[5] or meta[8:10]!=BASE_META[8:10] or
          meta[6:8]!=(len(data),zlib.crc32(data)) or
          meta[2:5] not in ((2,1,1),(1,0,0),(2,0,0))):
        raise RuntimeError('Unexpected A trial metadata')
    if normally_confirmed and meta[2:5]!=(1,0,0):
        raise RuntimeError('Observed confirmed A not retained in final metadata')
    return meta


def trial(row, run, data, receipt):
    expected,before=load_stage(receipt,data)
    port=uart=None
    try:
        port=open_port()
        uart=Console(port)
        row.update(hardware_attempted=True,trial_requests=1)
        debug(row,trial_commands(PRIVATE/(run+'-before.bin'),expected,data))
        row['activation_submitted']=True
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            try:
                fw=fields(uart.query('FW STATUS',.6))
            except TimeoutError:
                continue
            row['last_fw']=fw
            if fw.get('CURRENT')=='B' and fw.get('PENDING')=='-':
                raise RuntimeError('Trace A rejected/rolled back; no retry')
            if fw.get('CURRENT')!='A':
                continue
            try:
                state=fields(uart.query('MOTOR TEST STATUS',.6))
            except TimeoutError:
                continue
            row['last_state']=state
            if state.get('STATE')=='4':
                row['sample']=sample(uart)
                raise RuntimeError('Trace A startup fault; no retry')
            if all(fw.get(k)==v for k,v in (('CONFIRMED','A'),('PENDING','-'),
                                            ('ATTEMPTS','0'),('ACTIVE','0'))):
                row['normally_confirmed']=True
                break
        else:
            raise TimeoutError('Normal A health confirmation absent')
        first=sample(uart)
        row['samples'].append(first)
        row['sample']=first
        if (first['profile'].get('NAME')!='RC_BOUNDARY_TRACE' or
                first['profile'].get('ADMISSION')!='0' or
                first['commit'].get('READY')!='0' or
                first['state'].get('SD')!='0' or first['state'].get('MOE')!='0'):
            raise RuntimeError('Trace identity/admission/output check failed')
        end=time.monotonic()+20
        while time.monotonic()<end:
            uart.poll(.05)
        last=sample(uart)
        row['samples'].append(last)
        row['sample']=last
        if (last['profile'].get('NAME')!='RC_BOUNDARY_TRACE' or
                last['state'].get('SD')!='0' or last['state'].get('MOE')!='0' or
                last['commit'].get('READY')!='0' or
                int(last['adc'].get('PAIRS','0'))<=int(first['adc'].get('PAIRS','0'))):
            raise RuntimeError('Trace no longer computing or output unexpectedly enabled')
        row.update(pass_=True,observed_seconds=last['host_time']-first['host_time'],
                   observed_pairs=int(last['adc']['PAIRS'])-int(first['adc']['PAIRS']),
                   motor_commands=0,physical_pwm_preload_deadline_verified=False)
        print('TRACE PASS: same-frame PWM boundary attribution captured; no motor START',flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try: row['off_ack']=uart.query('ANALOG SAFE',.8)
                    except BaseException as error: row['uart_off_error']=str(error)
                final=PRIVATE/(run+'-final.bin')
                emergency_off(row,final)
                actual=final.read_bytes()
                meta=compare_final(before,actual,data,row.get('normally_confirmed',False),
                                   row.get('activation_submitted',False))
                row.update(final_metadata=list(meta),final_sha256=digest(actual),
                           all_app_and_private_bytes_unchanged=True)
        finally:
            if uart:
                row.update(uart=uart.lines,host_motor_commands=uart.starts,
                           host_uart_trial_commits=uart.ends)
            if port and port.is_open: port.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--stage-inactive-a',action='store_true')
    modes.add_argument('--trial-from-stage',type=Path)
    modes.add_argument('--restore-confirmed-b',action='store_true')
    parser.add_argument('--drive-12v-off-motor-disconnected',action='store_true')
    parser.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args=parser.parse_args()
    data=image()
    if not args.stage_inactive_a and not args.trial_from_stage and not args.restore_confirmed_b:
        print('OFFLINE PASS: exact boundary A; no private/device access')
        return 0
    mode='restore' if args.restore_confirmed_b else 'trial' if args.trial_from_stage else 'stage'
    if (mode=='stage' and not args.drive_12v_off_motor_disconnected or
            mode=='trial' and not args.drive_12v_on_motor_disconnected or
            mode=='restore' and not args.drive_12v_off_motor_disconnected):
        parser.error('Physical supply/motor-disconnected phase required')
    run='rc-boundary-'+mode+'-'+str(time.time_ns())
    row=dict(pass_=False,mode=mode,image_sha256=SHA,image_bytes=SIZE,steps=[],samples=[],
             hardware_attempted=False,programming_attempted=False,trial_requests=0,
             motor_commands=0,force_confirmation=False,automatic_retry=False,
             direct_metadata_write=False,physical_pwm_preload_deadline_verified=False)
    try:
        if mode=='stage': stage(row,run,data)
        elif mode=='trial': trial(row,run,data,args.trial_from_stage)
        else: restore(row,run,data)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('FAILED: '+str(error),flush=True)
        if (row.get('programming_attempted') or row.get('restore_attempted')) and not row.get('final_cpu_halted'):
            try: emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup: row['cleanup_failure']=str(cleanup)
    finally:
        receipt=OUTPUT/(run+'.json')
        receipt.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(receipt),flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':
    raise SystemExit(main())
