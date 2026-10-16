"""Pinned output-locked deferred-plan A trial. Offline by default.

Stage/restore with drive power off; trial with drive powered and motor
disconnected. One bootloader trial only. No motor command or forced confirm.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

import rc_boundary_board_test as prior
from firmware_transfer_iap import image_info, fields
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from protected_closed_loop_acceptance import protected_state, timing, protection
from tighten_synthetic_swd_recovery import latest_meta

ROOT, OUTPUT, PRIVATE = prior.ROOT, prior.OUTPUT, prior.PRIVATE
BASE_RECEIPT = OUTPUT/'rc-boundary-lite-restore-1792130700845604500.json'
BASE_SHA = '232a34deba756ee471471bed78ae0b496648154c52b33974a76ef5b75406bdc8'
BASE_META = (1112493908,3,2,0,0,576,212196,1600390142,210916,453748590,0,1750365771)
B_SHA = '9fd54166df782cce3e737ecfebe67bc4aff8f15a005fca1f1136c91bb8786f44'
IMAGE = ROOT/'foc2_app_a/build/RcDeferredShadow/foc2.bin'
SHA = '6cec5bac9231fbb5199a0173db535512c283f41626733b4b39a9bc61bdd74fae'
SIZE = 211340
PREFIX = 'rc-deferred-shadow-'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image():
    data = IMAGE.read_bytes()
    if len(data) != SIZE or digest(data) != SHA or image_info(data)[0] != 'A':
        raise ValueError('Exact offline-tested deferred shadow A required')
    for marker in (b'NAME=RC_DEFERRED_SHADOW HARD_OFF=0 ADMISSION=0',
                   b'MOTOR TEST DEFERRED SHADOW=1 ADMISSION=0 PUBLISH=0',
                   b'MOTOR TEST REPAIR SNAP', b'ADC BOUNDARY LITE',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000'):
        if marker not in data:
            raise ValueError('Missing shadow/protection identity')
    return data


def baseline():
    row = json.loads(BASE_RECEIPT.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'restore' or
            row.get('final_sha256') != BASE_SHA or
            tuple(row.get('final_metadata',())) != BASE_META or
            any(row.get(k) is not True for k in ('final_cpu_halted',
                'final_outputs_off','all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact confirmed B576 restore receipt required')
    path = prior.private_path(row['recovered_backup'])
    raw = path.read_bytes()
    if (len(raw) != 0x80000 or digest(raw) != BASE_SHA or latest_meta(raw) != BASE_META or
            digest(raw[0x40000:0x40000+BASE_META[8]]) != B_SHA):
        raise ValueError('B576 full capture mismatch')
    return path, raw


def compare_stage(before, actual, data):
    if len(actual) != 0x80000 or actual[0x8000:0x8000+SIZE] != data:
        raise ValueError('Incomplete capture or inactive A image mismatch')
    end = 0x8000+SIZE
    page_end = (end+0x7ff)&~0x7ff
    if actual[end:page_end] != b'\xff'*(page_end-end):
        raise ValueError('Unexpected last A erase-page tail')
    if actual[:0x8000] != before[:0x8000] or actual[page_end:] != before[page_end:]:
        raise ValueError('Bytes outside inactive A erase pages changed')
    if latest_meta(actual) != BASE_META:
        raise ValueError('Staging changed boot metadata')


def stage_commands(live, expected, staged):
    return [*prior.off_gate(0x08040000), *full_compare_commands(live,expected),
        'reset halt',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
        *off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
        *off_report(), 'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
        'halt','shutdown']


def stage(row, run, data):
    expected, before = baseline()
    row['hardware_attempted'] = True
    inspection = PRIVATE/(run+'-inspection.bin')
    out = debug(row,[*prior.off_gate(0x08040000),*off_report(),
        f'dump_image {{{inspection.as_posix()}}} 0x08000000 0x80000','shutdown'])
    row['inspection_outputs'] = check_off(out,(0x08040000,))
    if inspection.read_bytes() != before:
        raise ValueError('Live Flash differs from last halted B576 capture')
    row['inspection_pass'] = True
    print('INSPECT PASS: exact confirmed B576; outputs off',flush=True)
    staged = PRIVATE/(run+'-staged.bin')
    row['programming_attempted'] = True
    out = debug(row,stage_commands(PRIVATE/(run+'-prewrite.bin'),expected,staged))
    row['staged_outputs'] = check_off(out,(0,0x08000000))
    actual = staged.read_bytes()
    compare_stage(before,actual,data)
    row.update(pass_=True,staged_backup=str(staged),staged_sha256=digest(actual),
        final_metadata=list(latest_meta(actual)),all_bytes_outside_a_pages_unchanged=True,
        final_outputs_off=True,final_cpu_halted=True,activation=False)
    print('STAGE PASS: deferred shadow A exact; B/private retained; not activated',flush=True)


def read_receipt(path, mode):
    path = Path(path).resolve()
    if path.parent != OUTPUT.resolve() or not path.name.startswith(PREFIX+mode+'-'):
        raise ValueError('Unexpected receipt path/profile')
    row = json.loads(path.read_text('utf-8'))
    if row.get('mode') != mode or row.get('image_sha256') != SHA:
        raise ValueError('Receipt identity mismatch')
    return row


def load_stage(path, data):
    row = read_receipt(path,'stage')
    if (row.get('pass_') is not True or row.get('activation') is not False or
            tuple(row.get('final_metadata',())) != BASE_META or
            any(row.get(k) is not True for k in ('inspection_pass',
                'all_bytes_outside_a_pages_unchanged','final_outputs_off','final_cpu_halted'))):
        raise ValueError('Exact unactivated shadow A stage required')
    capture = prior.private_path(row['staged_backup'])
    raw = capture.read_bytes()
    if digest(raw) != row.get('staged_sha256'):
        raise ValueError('Stage capture changed')
    _,before = baseline()
    compare_stage(before,raw,data)
    return capture,raw


def mailbox(data):
    if len(data) != SIZE or digest(data) != SHA:
        raise ValueError('Exact shadow A only')
    body = struct.pack('<7I',0x584f424d,1,2,2,1,SIZE,zlib.crc32(data))
    return struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))


class Console(prior.Console):
    READ = prior.Console.READ | frozenset(('ADC BOUNDARY LITE',
        'ADC BOUNDARY LITE FIRST','ADC BOUNDARY LITE WORST',
        'MOTOR TEST DEFERRED','MOTOR TEST REPAIR SNAP'))


def sample(uart):
    result = dict(host_time=time.monotonic())
    for key,command in (('fw','FW STATUS'),('profile','MOTOR TEST PROFILE'),
            ('state','MOTOR TEST STATUS'),('zero','MOTOR TEST ZERO'),
            ('timing','MOTOR TEST TIMING'),('adc','ADC TIMING'),
            ('commit','ADC COMMIT'),('protection','MOTOR TEST PROTECTION'),
            ('repair','MOTOR TEST REPAIR SNAP'),('deferred','MOTOR TEST DEFERRED'),
            ('fault','MOTOR TEST FAULT'),('encoder','ENC DIAG'),
            ('cost','MOTOR TEST COST'),('buffer','ADC BUFFER'),
            ('boundary','ADC BOUNDARY LITE'),('first','ADC BOUNDARY LITE FIRST'),
            ('worst','ADC BOUNDARY LITE WORST')):
        result[key] = fields(uart.query(command))
    return result


def validate_sample(s):
    if (s['profile'].get('NAME') != 'RC_DEFERRED_SHADOW' or
            s['profile'].get('ADMISSION') != '0' or s['commit'].get('READY') != '0'):
        raise RuntimeError('Shadow identity/admission mismatch')
    def line(key): return 'OK '+' '.join(f'{k}={v}' for k,v in s[key].items())
    protected_state(line('state'),ready=True)
    timing(line('timing'))
    protection(line('protection'))
    if s['fault'].get('VALID') != '0':
        raise RuntimeError('Fault evidence present')
    if s['zero'].get('STATE') != '3' or s['zero'].get('REASON') != '0':
        raise RuntimeError('Powered zero not ready')
    if (s['timing'].get('LATE') != '0' or not 0 < int(s['timing'].get('MAX_US','0')) < 50 or
            s['adc'].get('DWT') != '1' or not 0 < int(s['adc'].get('MAX_CYC','0')) < 8500 or
            s['adc'].get('MISS') != '0' or s['adc'].get('PF') != '0'):
        raise RuntimeError('Observed 50 us compute/IRQ budget failed')
    d = s['deferred']
    if any(d.get(k) != v for k,v in (('SHADOW','1'),('ADMISSION','0'),('PUBLISH','0'),
            ('STALE','0'),('UNSAFE','0'),('REJECTED','0'),('PLAN_FAIL','0'))):
        raise RuntimeError('Deferred freshness/planning failed')
    staged,taken = int(d.get('STAGED','0')),int(d.get('TAKEN','0'))
    if taken < 1000 or staged-taken not in (0,1) or d.get('VALID') != str(staged-taken):
        raise RuntimeError('Deferred plan handoff not demonstrated')
    b = s['buffer']
    if b.get('STK_VALID') != '1' or int(b.get('FREE_B','0')) < 256:
        raise RuntimeError('Statistics task stack margin failed')


def compare_final(before,actual,data,submitted):
    if (len(actual) != 0x80000 or actual[:0x7e800] != before[:0x7e800] or
            actual[0x7f800:] != before[0x7f800:]):
        raise RuntimeError('Trial changed application/private Flash')
    meta = latest_meta(actual)
    if not submitted:
        if meta != BASE_META: raise RuntimeError('Unsubmitted trial changed metadata')
    elif (meta[5] <= BASE_META[5] or meta[8:10] != BASE_META[8:10] or
            meta[6:8] != (SIZE,zlib.crc32(data)) or
            meta[2:5] not in ((2,1,1),(1,0,0),(2,0,0))):
        raise RuntimeError('Unexpected shadow A trial metadata')
    return meta


def trial(row,run,data,receipt):
    expected,before = load_stage(receipt,data)
    port = uart = None
    try:
        port = open_port()
        uart = Console(port)
        row.update(hardware_attempted=True,trial_requests=1)
        debug(row,[*prior.off_gate(0),*full_compare_commands(PRIVATE/(run+'-before.bin'),expected),
            'reset halt',*write_mailbox(mailbox(data)),'reset run','shutdown'])
        row['activation_submitted'] = True
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            try: fw = fields(uart.query('FW STATUS',.6))
            except TimeoutError: continue
            row['last_fw'] = fw
            if fw.get('CURRENT') == 'B' and fw.get('PENDING') == '-':
                raise RuntimeError('Shadow A rejected/rolled back; no retry')
            if fw.get('CURRENT') != 'A': continue
            try: state = fields(uart.query('MOTOR TEST STATUS',.6))
            except TimeoutError: continue
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = sample(uart)
                raise RuntimeError('Shadow A startup fault captured; no retry')
            if all(fw.get(k) == v for k,v in (('CONFIRMED','A'),('PENDING','-'),
                    ('ATTEMPTS','0'),('ACTIVE','0'))):
                row['normally_confirmed'] = True
                break
        else: raise TimeoutError('Normal shadow A health confirmation absent')
        first = sample(uart)
        row['sample'] = first
        row['samples'].append(first)
        validate_sample(first)
        end = time.monotonic()+20
        while time.monotonic() < end: uart.poll(.05)
        last = sample(uart)
        row['sample'] = last
        row['samples'].append(last)
        validate_sample(last)
        if (int(last['adc']['PAIRS']) <= int(first['adc']['PAIRS']) or
                int(last['deferred']['TAKEN']) <= int(first['deferred']['TAKEN'])):
            raise RuntimeError('ADC/plan progression stopped')
        row.update(pass_=True,compute_50us_pass=True,
            observed_seconds=last['host_time']-first['host_time'],
            observed_pairs=int(last['adc']['PAIRS'])-int(first['adc']['PAIRS']),
            compute_max_us=int(last['timing']['MAX_US']),
            irq_max_us=int(last['adc']['MAX_CYC'])/170.0)
        print('TRIAL PASS: deferred handoff and compute observed; output locked',flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try: row['off_ack'] = uart.query('ANALOG SAFE',.8)
                    except BaseException as error: row['uart_off_error'] = str(error)
                final = PRIVATE/(run+'-final.bin')
                emergency_off(row,final)
                actual = final.read_bytes()
                meta = compare_final(before,actual,data,row.get('activation_submitted',False))
                row.update(final_metadata=list(meta),final_sha256=digest(actual),
                    all_app_and_private_bytes_unchanged=True)
        finally:
            if uart: row.update(uart=uart.lines,host_motor_commands=uart.starts,
                                host_uart_trial_commits=uart.ends)
            if port and port.is_open: port.close()


def restore(row,run,data,receipt):
    previous = read_receipt(receipt,'trial')
    if (previous.get('activation_submitted') is not True or
            previous.get('host_motor_commands') != 0 or
            any(previous.get(k) is not True for k in ('final_cpu_halted',
                'final_outputs_off','all_app_and_private_bytes_unchanged'))):
        raise ValueError('Stopped shadow trial required')
    expected = prior.private_path(previous['final_backup'])
    before = expected.read_bytes()
    if digest(before) != previous.get('final_sha256'):
        raise ValueError('Trial capture changed')
    meta = latest_meta(before)
    if tuple(previous.get('final_metadata',())) != meta or meta[6:8] != (SIZE,zlib.crc32(data)):
        raise ValueError('Trial metadata mismatch')
    _,base = baseline()
    entry = struct.unpack_from('<I',base,0x40004)[0]&~1
    if not 0x08040000 <= entry < 0x0807e800: raise ValueError('B entry outside slot')
    body = struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    words = struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    recovered = PRIVATE/(run+'-recovered.bin')
    row.update(hardware_attempted=True,restore_attempted=True)
    out = debug(row,[*prior.off_gate(0x08008000),
        *full_compare_commands(PRIVATE/(run+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(words),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not halted at B entry"}}',
        *off_commands(),*off_report(),
        'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
        f'dump_image {{{recovered.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    row['recovered_outputs'] = check_off(out,(0x08040000,))
    actual = recovered.read_bytes()
    if actual[:0x7e800] != before[:0x7e800] or actual[0x7f800:] != before[0x7f800:]:
        raise RuntimeError('Restore changed app/private Flash')
    restored = latest_meta(actual)
    if restored[2:5] != (2,0,0) or restored[5] <= meta[5] or restored[6:10] != meta[6:10]:
        raise RuntimeError('Confirmed B restore metadata failed')
    row.update(pass_=True,recovered_backup=str(recovered),final_sha256=digest(actual),
        final_metadata=list(restored),all_app_and_private_bytes_unchanged=True,
        final_cpu_halted=True,final_outputs_off=True)
    print('RESTORE PASS: original confirmed B selected and halted at entry',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stage-inactive-a',action='store_true')
    modes.add_argument('--trial-from-stage',type=Path)
    modes.add_argument('--restore-from-trial',type=Path)
    parser.add_argument('--drive-12v-off-motor-disconnected',action='store_true')
    parser.add_argument('--drive-12v-on-motor-disconnected',action='store_true')
    args = parser.parse_args()
    data = image()
    if not (args.stage_inactive_a or args.trial_from_stage or args.restore_from_trial):
        print('OFFLINE PASS: pinned shadow A; no device/private access')
        return 0
    mode = 'restore' if args.restore_from_trial else 'trial' if args.trial_from_stage else 'stage'
    if ((mode in ('stage','restore') and not args.drive_12v_off_motor_disconnected) or
            (mode == 'trial' and not args.drive_12v_on_motor_disconnected)):
        parser.error('Actual power/motor-disconnected phase required')
    run = PREFIX+mode+'-'+str(time.time_ns())
    row = dict(pass_=False,mode=mode,image_sha256=SHA,image_bytes=SIZE,steps=[],samples=[],
        hardware_attempted=False,programming_attempted=False,trial_requests=0,motor_commands=0,
        force_confirmation=False,automatic_retry=False,direct_metadata_write=False,
        physical_pwm_preload_deadline_verified=False,motor_closed_loop_verified=False)
    try:
        if mode == 'stage': stage(row,run,data)
        elif mode == 'trial': trial(row,run,data,args.trial_from_stage)
        else: restore(row,run,data,args.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('FAILED: '+str(error),flush=True)
        if ((row.get('programming_attempted') or row.get('restore_attempted')) and
                not row.get('final_cpu_halted')):
            try: emergency_off(row,PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup: row['cleanup_failure'] = str(cleanup)
    finally:
        receipt = OUTPUT/(run+'.json')
        receipt.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(receipt),flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
