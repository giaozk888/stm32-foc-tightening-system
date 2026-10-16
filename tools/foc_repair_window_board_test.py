"""Pinned hard-off repair capture: separate OFF-stage and ON-trial phases.

Default is offline. No motor command, forced confirmation, direct metadata
write or retry. Only failed unconfirmed A is replaced; confirmed B is retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

import zero_compact_board_test as old
import foc_repair_window_capture as capture

base = old.base
OUTPUT, PRIVATE = base.OUTPUT, base.PRIVATE
PRIOR = OUTPUT / 'zero-compact-trial-1792063950718386700.json'
BASELINE_SHA = 'f88f9fa3cfdc0debd4e76c389eca0941d2dd4dc5ad7deaede62e31bc125e88aa'
META = (1112493908, 3, 2, 1, 1, 555, 208228, 22138867,
        208564, 4225420029, 0, 582067096)
IMAGE = base.old.ROOT / 'foc2_app_a/build/RepairWindowDiagnostic/foc2.bin'
SHA = 'fd6e3c1530ac23ab9bd72f7d812adacccfe437cbaa9feed4764abd8c1c19f2b0'
SIZE = 209820
PREFIX = 'repair-window-'


def pinned_image():
    image = IMAGE.read_bytes()
    if len(image) != SIZE or hashlib.sha256(image).hexdigest() != SHA or base.image_info(image)[0] != 'A':
        raise ValueError('Exact repair-window hard-off A required')
    for identity in (b'OK REPAIR ENABLED=1 HARD_OFF=1 N=32', b'MOTOR TEST REPAIR ROW ',
            b'COMPACT ENABLED=1 HARD_OFF=1 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50',
            b'ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1', b'MAX=OFF SEG_MAX=OFF'):
        if identity not in image:
            raise ValueError('Diagnostic identity missing')
    return image


def load_before():
    row = json.loads(PRIOR.read_text('utf-8'))
    path = Path(row['final_backup']).resolve()
    if (path.parent != PRIVATE.resolve() or row.get('final_sha256') != BASELINE_SHA
            or row.get('image_sha256') != old.SHA or row.get('motor_commands') != 0
            or row.get('trial_requests') != 1 or row.get('pass_') is not False
            or tuple(row.get('final_metadata', ())) != META
            or any(row.get(k) is not True for k in ('final_outputs_off', 'final_cpu_halted',
                                                   'all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact failed compact A / confirmed B receipt required')
    raw = path.read_bytes()
    if (len(raw) != 0x80000 or hashlib.sha256(raw).hexdigest() != BASELINE_SHA
            or base.latest_meta(raw) != META or raw[0x8000:0x8000+old.SIZE] != old.pinned_image()
            or hashlib.sha256(raw[0x40000:0x40000+META[8]]).hexdigest() != base.old.B_SHA):
        raise ValueError('Exact stopped baseline changed')
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
        raise ValueError('Stage changed metadata')
    row.update(pass_=True, staged_backup=str(staged), staged_sha256=hashlib.sha256(actual).hexdigest(),
        metadata_unchanged=True, all_bytes_outside_a_unchanged=True, cpu_reset_halted=True,
        final_cpu_halted=True, final_outputs_off=True, activation=False)
    print('STAGE PASS: repair diagnostic A; B/bootloader/private retained; NOT activated', flush=True)


def load_stage(path):
    path = path.resolve()
    if path.parent != OUTPUT.resolve() or not path.name.startswith(PREFIX + 'stage-'):
        raise ValueError('Exact repair stage receipt required')
    row = json.loads(path.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage'
            or row.get('image_sha256') != SHA or row.get('activation') is not False
            or row.get('motor_commands') != 0
            or any(row.get(k) is not True for k in ('metadata_unchanged', 'all_bytes_outside_a_unchanged',
                                                   'cpu_reset_halted', 'final_outputs_off'))):
        raise ValueError('Exact unactivated repair stage required')
    private = Path(row['staged_backup']).resolve()
    if private.parent != PRIVATE.resolve():
        raise ValueError('Private capture location mismatch')
    raw = private.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['staged_sha256'] or base.latest_meta(raw) != META:
        raise ValueError('Stage capture changed')
    _, before = load_before()
    base.unchanged_except_a(before, raw, pinned_image())
    return private, raw


def trial_commands(live, path):
    image = pinned_image()
    body = struct.pack('<7I', 0x584F424D, 1, 2, 2, 1, len(image), zlib.crc32(image))
    words = struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))
    gate = base.output_gate(0)
    gate[2] = 'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not bootloader"}'
    return [*gate, *base.full_compare_commands(live, path), 'reset halt',
            *base.write_mailbox(words), 'reset run', 'shutdown']


def trial(row, run, image, stage_path):
    path, before = load_stage(stage_path)
    port = uart = None
    try:
        port = base.open_port()
        uart = capture.Console(port)
        row.update(hardware_attempted=True, trial_requests=1)
        base.debug(row, trial_commands(PRIVATE / (run + '-before.bin'), path))
        print('ONE hard-off A diagnostic; no START; no automatic retry', flush=True)
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            row['fw'] = fw
            f = base.fields(fw)
            if f.get('CURRENT') == 'B':
                raise ValueError('Fallback B selected; no retry')
            if f.get('CURRENT') != 'A':
                continue
            state = base.fields(uart.query('MOTOR TEST STATUS', .8))
            row['last_state'] = state
            if state.get('STATE') == '4':
                # Read the frozen evidence BEFORE any cleanup/reset.
                try:
                    row.update(capture.collect(uart, row))
                finally:
                    row['sample'] = old.snapshot(uart)
                row['pass_'] = True  # Capture success, never motor/timing acceptance.
                print('CAPTURE PASS: ' + row['cause'], flush=True)
                return
            uart.poll(.02)
            # poll() can return immediately on continuous unsolicited output.
            # Limit request frequency explicitly instead of saturating UART.
            time.sleep(.1)
        row['summary_line'] = uart.query('MOTOR TEST REPAIR')
        row['summary'] = base.fields(row['summary_line'])
        row['sample'] = old.snapshot(uart)
        raise TimeoutError('No repair fault reproduced within the single bounded trial')
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try:
                        row['off_ack'] = base.Console.query(uart, 'ANALOG SAFE', .8)
                    except Exception as error:
                        row['uart_off_error'] = str(error)
                final = PRIVATE / (run + '-final.bin')
                base.emergency_off(row, final)
                actual = final.read_bytes()
                if actual[:0x7E800] != before[:0x7E800] or actual[0x7F800:] != before[0x7F800:]:
                    raise ValueError('Trial changed APP/bootloader/private bytes')
                base.unchanged_except_a(before, actual, image, metadata_allowed=True)
                meta = base.latest_meta(actual)
                if (meta[5] <= META[5] or meta[2:5] not in ((2, 1, 1), (1, 0, 0))
                        or meta[6:8] != (len(image), zlib.crc32(image))):
                    raise ValueError('Unexpected normal trial metadata')
                row.update(all_app_and_private_bytes_unchanged=True, final_metadata=list(meta),
                           final_sha256=hashlib.sha256(actual).hexdigest())
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
        print('OFFLINE PASS: exact repair diagnostic A; no hardware/private access')
        return
    if (args.stage_failed_a and not args.drive_12v_off) or (args.trial_from and not args.drive_12v_on):
        parser.error('Actual power state required')
    mode = 'stage' if args.stage_failed_a else 'trial'
    run = PREFIX + mode + '-' + str(time.time_ns())
    row = dict(pass_=False, mode=mode, image_sha256=SHA, image_bytes=SIZE, steps=[],
        motor_commands=0, automatic_retry=False, force_confirmation=False, direct_metadata_write=False,
        hardware_attempted=False, capture_valid=False, timing_acceptance=False, motor_acceptance=False,
        baseline_receipt=str(PRIOR))
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
