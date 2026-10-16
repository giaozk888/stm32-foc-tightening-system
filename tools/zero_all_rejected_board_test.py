"""Pinned all-rejected ZERO DIAGNOSTIC, bridge hard-off; no motor commands.

Default offline. Stage only replaces failed, unconfirmed A while confirmed B
is retained. Trial is a separate explicit phase after physical 12 V is on.
No direct Flash metadata writes, force confirmation, fault clear or retries.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

import foc_startup_evidence_stage as old
from firmware_transfer_iap import image_info, fields
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from protected_irq_timing_acceptance import TimingConsole
from tighten_synthetic_swd_recovery import latest_meta

OUTPUT, PRIVATE = old.OUTPUT, old.PRIVATE
PRIOR = OUTPUT / 'startup-evidence-a-compute-1792060167970913800.json'
BASELINE_SHA = '329d11f144b97f4383253ba6eaa93384e7932c168ea19a457669009f564b43d1'
IMAGE = old.ROOT / 'foc2_app_a/build/ZeroAllRejectedDiagnostic/foc2.bin'
SHA = '9035539aabd09609914e39c13cb5170d18e709efc2ae1269c71accab55ef51e8'
SIZE = 207444
META = (1112493908, 3, 2, 1, 1, 551, 211004, 1641801763,
        208564, 4225420029, 0, 608211323)


def pinned_image():
    image = IMAGE.read_bytes()
    if len(image) != SIZE or hashlib.sha256(image).hexdigest() != SHA or image_info(image)[0] != 'A':
        raise RuntimeError('Exact hard-off all-rejected A required')
    for marker in (b'DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V',
                   b'ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1', b'MAX=OFF SEG_MAX=OFF',
                   b'RAM ENABLED=1 HARD_OFF=1 DEADLINE_US=50'):
        if marker not in image:
            raise RuntimeError('Required diagnostic/hard-off identity missing')
    return image


def load_before():
    row = json.loads(PRIOR.read_text('utf-8'))
    path = Path(row['final_backup']).resolve()
    if (path.parent != PRIVATE.resolve() or row.get('final_sha256') != BASELINE_SHA
            or row.get('image_sha256') != old.SHA or row.get('motor_commands') != 0
            or any(row.get(k) is not True for k in ('final_outputs_off', 'final_cpu_halted',
                                                   'all_app_and_private_bytes_unchanged'))
            or tuple(row.get('final_metadata', ())) != META):
        raise RuntimeError('Exact stopped failed A / confirmed B baseline required')
    raw = path.read_bytes()
    if (len(raw) != 0x80000 or hashlib.sha256(raw).hexdigest() != BASELINE_SHA
            or latest_meta(raw) != META or raw[0x8000:0x8000 + old.SIZE] != old.pinned_image()
            or hashlib.sha256(raw[0x40000:0x40000 + META[8]]).hexdigest() != old.B_SHA):
        raise RuntimeError('Failed A / confirmed B capture mismatch')
    return path, raw


def unchanged_except_a(before, actual, image, *, metadata_allowed=False):
    if len(before) != 0x80000 or len(actual) != 0x80000 or actual[0x8000:0x8000 + len(image)] != image:
        raise RuntimeError('Full capture / exact A image mismatch')
    if (before[:0x8000] != actual[:0x8000] or before[0x40000:0x7E800] != actual[0x40000:0x7E800]
            or before[0x7F800:] != actual[0x7F800:]):
        raise RuntimeError('Bootloader/B/private Flash changed')
    if not metadata_allowed and before[0x7E800:0x7F800] != actual[0x7E800:0x7F800]:
        raise RuntimeError('Stage changed Flash metadata')
    if latest_meta(actual)[8:10] != META[8:10]:
        raise RuntimeError('Preserved B metadata changed')


def output_gate(vtor):
    return ['init',
        'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not already halted"}',
        f'if {{[mrw 0xE000ED08] != {vtor:#x}}} {{error "Unexpected halted slot"}}',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Outputs not off"}']


def stage_commands(live, baseline, staged):
    return [*output_gate(0x08008000), *full_compare_commands(live, baseline),
        'reset halt',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not bootloader"}',
        *off_commands(), f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000', *off_report(),
        'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}', 'halt', 'shutdown']


def stage(row, run, image):
    path, before = load_before()
    staged = PRIVATE / (run + '-staged.bin')
    row['hardware_attempted'] = True
    output = debug(row, stage_commands(PRIVATE / (run + '-before.bin'), path, staged))
    row['outputs'] = check_off(output, (0, 0x08000000))
    actual = staged.read_bytes()
    unchanged_except_a(before, actual, image)
    if latest_meta(actual) != META:
        raise RuntimeError('Unexpected stage metadata')
    row.update(pass_=True, staged_backup=str(staged), staged_sha256=hashlib.sha256(actual).hexdigest(),
               metadata_unchanged=True, all_bytes_outside_a_unchanged=True,
               cpu_reset_halted=True, final_outputs_off=True, activation=False)
    print('STAGE PASS: diagnostic A exact; B/bootloader/data preserved; NOT activated', flush=True)


def load_stage(path):
    path = path.resolve()
    if path.parent != OUTPUT.resolve() or not path.name.startswith('zero-all-rejected-stage-'):
        raise RuntimeError('Expected all-rejected stage receipt')
    row = json.loads(path.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage' or row.get('image_sha256') != SHA
            or row.get('activation') is not False or row.get('motor_commands') != 0
            or any(row.get(k) is not True for k in ('metadata_unchanged', 'all_bytes_outside_a_unchanged',
                                                   'cpu_reset_halted', 'final_outputs_off'))):
        raise RuntimeError('Exact unactivated all-rejected A stage required')
    capture = Path(row['staged_backup']).resolve()
    if capture.parent != PRIVATE.resolve():
        raise RuntimeError('Private capture path mismatch')
    raw = capture.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['staged_sha256'] or latest_meta(raw) != META:
        raise RuntimeError('Stage changed')
    _, before = load_before()
    unchanged_except_a(before, raw, pinned_image())
    return capture, raw


def trial_commands(live, path):
    image = pinned_image()
    body = struct.pack('<7I', 0x584F424D, 1, 2, 2, 1, len(image), zlib.crc32(image))
    words = struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))
    commands = output_gate(0)
    commands[2] = 'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}'
    return [*commands, *full_compare_commands(live, path), 'reset halt',
            *write_mailbox(words), 'reset run', 'shutdown']


class Console(TimingConsole):
    READ = TimingConsole.READ | frozenset(('MOTOR TEST ZERO POLICY', 'MOTOR TEST ZERO ROBUST',
        'MOTOR TEST FILTER', 'MOTOR TEST RAM'))

    def query(self, text, timeout=2):
        if text not in self.READ and text != 'ANALOG SAFE':
            raise ValueError('Read/off only; no START, trial commits, fault clears or resets')
        return super().query(text, timeout)


def snapshot(uart):
    row = {}
    for key, cmd in (('state', 'MOTOR TEST STATUS'), ('zero', 'MOTOR TEST ZERO'),
        ('robust', 'MOTOR TEST ZERO ROBUST'), ('policy', 'MOTOR TEST ZERO POLICY'),
        ('filter', 'MOTOR TEST FILTER'), ('timing', 'MOTOR TEST TIMING'), ('adc', 'ADC TIMING'),
        ('protection', 'MOTOR TEST PROTECTION'), ('fault', 'MOTOR TEST FAULT'),
        ('cost', 'MOTOR TEST COST'), ('late', 'MOTOR TEST LATE'), ('buffer', 'ADC BUFFER'),
        ('ram', 'MOTOR TEST RAM'), ('status', 'STATUS')):
        row[key] = fields(uart.query(cmd))
    row['encoder'] = uart.encoder_diag()
    return row


def validate_zero(row):
    for key, expected in (
        ('state', dict(STATE='1', ARMED='1', FLAGS='0', FAULT='0', SD='0', MOE='0', CCER='0')),
        ('zero', dict(STATE='3', REASON='0', N='4000')),
        ('robust', dict(SEGMENTS='8', FLAGS='0', MAX='OFF', SEG_MAX='OFF', HARD_OFF='1')),
        ('policy', dict(DIAGNOSTIC='1', HARD_OFF='1', BURST='ALL_REJECTED', BLOCK='5', DELTA='40', PAIR='U_OR_V')),
        ('filter', dict(ADAPT='1', HARD_OFF='1')),
        ('ram', dict(ENABLED='1', HARD_OFF='1', DEADLINE_US='50'))):
        if any(row[key].get(k) != v for k, v in expected.items()):
            raise RuntimeError('Zero diagnostic acceptance failed: ' + key)


def validate_confirmed_metadata(meta, image):
    if (meta[2:5] != (1, 0, 0) or meta[5] <= META[5]
            or meta[6:8] != (len(image), zlib.crc32(image))
            or meta[8:10] != META[8:10]):
        raise RuntimeError('Final metadata does not confirm exact diagnostic A / preserve B')


def trial(row, run, image, stage_path):
    path, before = load_stage(stage_path)
    port = uart = None
    try:
        port = open_port()
        uart = Console(port)
        row['hardware_attempted'] = True
        row['trial_requests'] = 1
        debug(row, trial_commands(PRIVATE / (run + '-before.bin'), path))
        print('ONE hard-off A trial; ZERO comparison only; no START', flush=True)
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            row['fw'] = fw
            f = fields(fw)
            if f.get('CURRENT') == 'B':
                raise RuntimeError('Fallback B selected; no retry')
            if f.get('CURRENT') != 'A':
                continue
            try:
                state = fields(uart.query('MOTOR TEST STATUS', .6))
            except TimeoutError:
                continue
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = snapshot(uart)
                raise RuntimeError('Diagnostic startup fault; no retry')
            if f.get('CONFIRMED') == 'A' and f.get('PENDING') == '-' and f.get('ATTEMPTS') == '0':
                break
        else:
            raise TimeoutError('Normal trial confirmation absent')
        row['sample'] = snapshot(uart)
        validate_zero(row['sample'])
        row.update(zero_pass=True, pass_=True)
        print('ZERO PASS: full 4000-pair window and exact all-rejected policy; output hard-off', flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try:
                        row['off_ack'] = uart.query('ANALOG SAFE', .8)
                    except BaseException as error:
                        row['uart_off_error'] = str(error)
                final = PRIVATE / (run + '-final.bin')
                emergency_off(row, final)
                actual = final.read_bytes()
                if actual[:0x7E800] != before[:0x7E800] or actual[0x7F800:] != before[0x7F800:]:
                    raise RuntimeError('Trial changed APP/bootloader/private bytes')
                unchanged_except_a(before, actual, image, metadata_allowed=True)
                meta = latest_meta(actual)
                row.update(all_app_and_private_bytes_unchanged=True,
                           final_metadata=list(meta), final_sha256=hashlib.sha256(actual).hexdigest())
                if row.get('zero_pass'):
                    validate_confirmed_metadata(meta, image)
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
    parser.add_argument('--drive-12v-off', action='store_true')
    parser.add_argument('--drive-12v-on', action='store_true')
    args = parser.parse_args()
    image = pinned_image()
    if not args.stage_failed_a and not args.trial_from:
        print('OFFLINE PASS: pinned hard-off all-rejected A; no hardware access')
        return
    if (args.stage_failed_a and not args.drive_12v_off) or (args.trial_from and not args.drive_12v_on):
        parser.error('Actual power state required for selected phase')
    mode = 'stage' if args.stage_failed_a else 'trial'
    run = 'zero-all-rejected-' + mode + '-' + str(time.time_ns())
    row = dict(pass_=False, mode=mode, image_sha256=SHA, image_bytes=SIZE, steps=[],
        motor_commands=0, automatic_retry=False, force_confirmation=False, direct_metadata_write=False,
        hardware_attempted=False, baseline_receipt=str(PRIOR))
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
                emergency_off(row)
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        receipt = OUTPUT / (run + '.json')
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(mode.upper() + ' ' + ('PASS' if row['pass_'] else 'FAIL'), flush=True)
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
