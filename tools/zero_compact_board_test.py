"""Pinned compact ZERO/FOC hard-off comparison. Default: offline only.

Stage replaces only failed/unconfirmed A, retaining confirmed B. Separate trial
performs one normal bootloader request, no START, no forced confirmation/retry.
All full-Flash captures stay under the existing restricted private directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

import zero_all_rejected_board_test as base

OUTPUT, PRIVATE = base.OUTPUT, base.PRIVATE
PRIOR = OUTPUT / 'zero-all-rejected-trial-1792063086911802700.json'
BASELINE_SHA = '98949d3a13eb2318692ccc9cdca60671cd4be32345aaad853824b6c5cf718cd1'
IMAGE = base.old.ROOT / 'foc2_app_a/build/ZeroAllRejectedCompact/foc2.bin'
SHA = '9dff17fff93046487193fb23c6c07aef1940e4e715b0df0b85b3747961a754d1'
SIZE = 208228
META = (1112493908, 3, 2, 1, 1, 553, 207444, 2407456200,
        208564, 4225420029, 0, 3453336315)
PREFIX = 'zero-compact-'
OBSERVE_SECONDS = 30.0


def pinned_image():
    data = IMAGE.read_bytes()
    if (len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA
            or base.image_info(data)[0] != 'A'):
        raise RuntimeError('Exact compact hard-off A required')
    for marker in (b'DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V',
                   b'COMPACT ENABLED=1 HARD_OFF=1 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50',
                   b'ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1', b'MAX=OFF SEG_MAX=OFF',
                   b'RAM ENABLED=1 HARD_OFF=1 DEADLINE_US=50'):
        if marker not in data:
            raise RuntimeError('Compact hard-off identity missing')
    return data


def load_before():
    row = json.loads(PRIOR.read_text('utf-8'))
    path = Path(row['final_backup']).resolve()
    if (path.parent != PRIVATE.resolve() or row.get('final_sha256') != BASELINE_SHA
            or row.get('image_sha256') != base.SHA or row.get('motor_commands') != 0
            or row.get('trial_requests') != 1 or row.get('pass_') is not False
            or any(row.get(k) is not True for k in ('final_outputs_off', 'final_cpu_halted',
                                                   'all_app_and_private_bytes_unchanged'))
            or tuple(row.get('final_metadata', ())) != META):
        raise RuntimeError('Exact failed/halted A / confirmed B receipt required')
    raw = path.read_bytes()
    if (len(raw) != 0x80000 or hashlib.sha256(raw).hexdigest() != BASELINE_SHA
            or base.latest_meta(raw) != META
            or raw[0x8000:0x8000 + base.SIZE] != base.pinned_image()
            or hashlib.sha256(raw[0x40000:0x40000 + META[8]]).hexdigest() != base.old.B_SHA):
        raise RuntimeError('Failed A / confirmed B capture mismatch')
    return path, raw


def stage_commands(live, baseline, staged):
    return [*base.output_gate(0x08008000), *base.full_compare_commands(live, baseline),
        'reset halt',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not bootloader"}',
        *base.off_commands(), f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000', *base.off_report(),
        'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}', 'halt', 'shutdown']


def stage(row, run, image):
    path, before = load_before()
    staged = PRIVATE / (run + '-staged.bin')
    row['hardware_attempted'] = True
    result = base.debug(row, stage_commands(PRIVATE / (run + '-before.bin'), path, staged))
    row['outputs'] = base.check_off(result, (0, 0x08000000))
    actual = staged.read_bytes()
    base.unchanged_except_a(before, actual, image)
    if base.latest_meta(actual) != META:
        raise RuntimeError('Unexpected stage metadata')
    row.update(pass_=True, staged_backup=str(staged), staged_sha256=hashlib.sha256(actual).hexdigest(),
        metadata_unchanged=True, all_bytes_outside_a_unchanged=True, cpu_reset_halted=True,
        final_cpu_halted=True, final_outputs_off=True, activation=False)
    print('STAGE PASS: compact A exact; B/bootloader/data preserved; NOT activated', flush=True)


def load_stage(path):
    path = path.resolve()
    if path.parent != OUTPUT.resolve() or not path.name.startswith(PREFIX + 'stage-'):
        raise RuntimeError('Expected exact compact stage receipt')
    row = json.loads(path.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage'
            or row.get('image_sha256') != SHA or row.get('activation') is not False
            or row.get('motor_commands') != 0
            or any(row.get(k) is not True for k in ('metadata_unchanged', 'all_bytes_outside_a_unchanged',
                                                   'cpu_reset_halted', 'final_outputs_off'))):
        raise RuntimeError('Unactivated compact A stage required')
    capture = Path(row['staged_backup']).resolve()
    if capture.parent != PRIVATE.resolve():
        raise RuntimeError('Private capture path mismatch')
    raw = capture.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['staged_sha256'] or base.latest_meta(raw) != META:
        raise RuntimeError('Stage changed')
    _, before = load_before()
    base.unchanged_except_a(before, raw, pinned_image())
    return capture, raw


def trial_commands(live, path):
    image = pinned_image()
    body = struct.pack('<7I', 0x584F424D, 1, 2, 2, 1, len(image), zlib.crc32(image))
    words = struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))
    commands = base.output_gate(0)
    commands[2] = 'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}'
    return [*commands, *base.full_compare_commands(live, path), 'reset halt',
            *base.write_mailbox(words), 'reset run', 'shutdown']


class Console(base.Console):
    READ = base.Console.READ | frozenset(('MOTOR TEST COMPACT',))


def snapshot(uart):
    row = base.snapshot(uart)
    row['compact'] = base.fields(uart.query('MOTOR TEST COMPACT'))
    row['host_time'] = time.monotonic()
    return row


def validate_sample(row):
    base.validate_zero(row)
    required = dict(ENABLED='1', HARD_OFF='1', FIXED_OPS='1', GUARD_US='25', DEADLINE_US='50')
    if any(row['compact'].get(k) != v for k, v in required.items()):
        raise RuntimeError('Not exact compact diagnostic profile')
    t, a = row['timing'], row['adc']
    if (int(t['WORK']) < 1000 or not 0 < int(t['MAX_US']) < 50 or t['LATE'] != '0'
            or a['DWT'] != '1' or a['MISS'] != '0' or a['PF'] != '0'
            or a['LATE'] != '0' or not 0 < int(a['MAX_CYC']) < 8500):
        raise RuntimeError('50 us FOC/ADC timing acceptance failed')
    if row['fault'].get('VALID') != '0' or row['status'].get('FLT') != '0':
        raise RuntimeError('FOC/fault status not clear')
    b = row['buffer']
    if b.get('STK_VALID') != '1' or int(b.get('FREE_B', '0')) < 256 or int(b.get('DONE', '0')) < 1:
        raise RuntimeError('Background double-buffer worker not validated')
    if any(row['encoder']['dma'].get(k) != '0' for k in ('FAIL', 'TIMEOUT', 'IO', 'SCHED', 'STALE')):
        raise RuntimeError('Encoder DMA fault')


def validate_progress(first, last):
    if last['host_time'] - first['host_time'] < OBSERVE_SECONDS:
        raise RuntimeError('Observation shorter than 30 seconds')
    for key, field in (('timing', 'WORK'), ('timing', 'OUTER'), ('adc', 'PAIRS'), ('buffer', 'DONE')):
        if int(last[key][field]) <= int(first[key][field]):
            raise RuntimeError('Work/ADC/outer/worker stopped: ' + field)


def trial(row, run, image, stage_path):
    path, before = load_stage(stage_path)
    port = uart = None
    try:
        port = base.open_port()
        uart = Console(port)
        row.update(hardware_attempted=True, trial_requests=1)
        base.debug(row, trial_commands(PRIVATE / (run + '-before.bin'), path))
        print('ONE compact hard-off A trial; no START; no retry', flush=True)
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            row['fw'] = fw
            f = base.fields(fw)
            if f.get('CURRENT') == 'B':
                raise RuntimeError('Fallback B selected; no retry')
            if f.get('CURRENT') != 'A':
                continue
            try:
                state = base.fields(uart.query('MOTOR TEST STATUS', .6))
            except TimeoutError:
                continue
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = snapshot(uart)
                raise RuntimeError('Compact startup fault; no retry')
            if f.get('CONFIRMED') == 'A' and f.get('PENDING') == '-' and f.get('ATTEMPTS') == '0':
                break
        else:
            raise TimeoutError('Normal health confirmation absent')
        first = snapshot(uart)
        row['samples'] = [first]
        row['sample'] = first
        validate_sample(first)
        print('Startup/zero PASS; beginning 30-second compute-only observation', flush=True)
        while True:
            uart.poll(.2)
            sample = snapshot(uart)
            row['samples'].append(sample)
            row['sample'] = sample
            validate_sample(sample)
            if sample['host_time'] - first['host_time'] >= OBSERVE_SECONDS:
                break
        validate_progress(first, sample)
        row.update(pass_=True, zero_pass=True, compute_timing_pass=True,
                   observed_seconds=sample['host_time'] - first['host_time'],
                   compute_max_us=int(sample['timing']['MAX_US']),
                   adc_max_us=int(sample['adc']['MAX_CYC']) / 170.0)
        print('COMPUTE PASS: sustained 30 seconds, FOC/ADC below 50 us; output hard-off', flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try:
                        row['off_ack'] = uart.query('ANALOG SAFE', .8)
                    except BaseException as error:
                        row['uart_off_error'] = str(error)
                final = PRIVATE / (run + '-final.bin')
                base.emergency_off(row, final)
                actual = final.read_bytes()
                if actual[:0x7E800] != before[:0x7E800] or actual[0x7F800:] != before[0x7F800:]:
                    raise RuntimeError('Trial changed APP/bootloader/private bytes')
                base.unchanged_except_a(before, actual, image, metadata_allowed=True)
                meta = base.latest_meta(actual)
                row.update(all_app_and_private_bytes_unchanged=True,
                           final_metadata=list(meta), final_sha256=hashlib.sha256(actual).hexdigest())
                if row.get('compute_timing_pass'):
                    base.validate_confirmed_metadata(meta, image)
                    if meta[5] <= META[5]:
                        raise RuntimeError('Compact trial metadata generation invalid')
        finally:
            if uart:
                row['uart'] = uart.lines
            if port and port.is_open:
                port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stage-failed-a', action='store_true')
    modes.add_argument('--trial-from', type=Path)
    power = parser.add_mutually_exclusive_group()
    power.add_argument('--drive-12v-off', action='store_true')
    power.add_argument('--drive-12v-on', action='store_true')
    args = parser.parse_args()
    image = pinned_image()
    if not args.stage_failed_a and not args.trial_from:
        print('OFFLINE PASS: exact compact hard-off A; no hardware/private access')
        return
    if (args.stage_failed_a and not args.drive_12v_off) or (args.trial_from and not args.drive_12v_on):
        parser.error('Actual power state required for selected phase')
    mode = 'stage' if args.stage_failed_a else 'trial'
    run = PREFIX + mode + '-' + str(time.time_ns())
    row = dict(pass_=False, mode=mode, image_sha256=SHA, image_bytes=SIZE, steps=[],
        motor_commands=0, automatic_retry=False, force_confirmation=False, direct_metadata_write=False,
        hardware_attempted=False, baseline_receipt=str(PRIOR), requested_observation_seconds=OBSERVE_SECONDS)
    try:
        if mode == 'stage':
            stage(row, run, image)
        else:
            row['stage_receipt'] = str(args.trial_from.resolve())
            trial(row, run, image, args.trial_from)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        print('FAILED: ' + str(error), flush=True)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:
                base.emergency_off(row)
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        receipt = OUTPUT / (run + '.json')
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(mode.upper() + (' PASS' if row['pass_'] else ' FAIL'), flush=True)
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
