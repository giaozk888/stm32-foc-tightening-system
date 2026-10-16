"""One pinned A startup-evidence trial, COMPUTATION ONLY: never motor START.

No APP programming, forced confirmation, fault clear, setpoint or retries.
The existing bootloader and normal APP health gate own trial/confirmation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

import foc_startup_evidence_stage as stage
from firmware_transfer_iap import fields
from latest_original_fsm_acceptance import Console as OriginalConsole, validate
from latest_original_fsm_stage import full_compare_commands, write_mailbox
from original_closed_loop_trial import emergency_off
from original_closed_loop_updated_stage import debug
from protected_compact_closed_loop_acceptance import sample
from protected_irq_optimized_stage import open_port
from tighten_synthetic_swd_recovery import latest_meta
from zero_retest_deploy import compare_flash

STAGED = stage.OUTPUT / 'startup-evidence-a-stage-1792059910937437500.json'


class Console(OriginalConsole):
    READ = OriginalConsole.READ | frozenset(('MOTOR TEST STARTUP CONFIG',
        'MOTOR TEST STARTUP', 'MOTOR TEST STARTUP FAULT'))


def trial_words():
    data = stage.pinned_image()
    body = struct.pack('<7I', 0x584F424D, 1, 2, 2, 1, len(data), zlib.crc32(data))
    return struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))


def load_stage():
    row = json.loads(STAGED.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('image_sha256') != stage.SHA
            or row.get('target') != 'A' or row.get('confirmed_retained') != 'B549'
            or row.get('activation') is not False or row.get('motor_commands') != 0
            or row.get('trial_mailbox_write') is not False
            or any(row.get(key) is not True for key in
                   ('metadata_unchanged', 'all_bytes_outside_a_unchanged',
                    'cpu_reset_halted', 'final_outputs_off'))):
        raise RuntimeError('Exact successful unactivated A-stage receipt required')
    path = Path(row['staged_backup']).resolve()
    if path.parent != stage.PRIVATE.resolve():
        raise RuntimeError('Private stage path mismatch')
    raw = path.read_bytes()
    if (hashlib.sha256(raw).hexdigest() != row['staged_sha256']
            or latest_meta(raw) != stage.META):
        raise RuntimeError('Stage capture/metadata changed')
    compare_flash(raw, raw, stage.pinned_image(), 'A', staged=True)
    return path, raw


def activation_commands(live, baseline):
    return ['init',
        'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Outputs not off"}',
        *full_compare_commands(live, baseline), 'reset halt',
        *write_mailbox(trial_words()), 'reset run', 'shutdown']


def require_ready(fw, health, status, safe):
    f, h, s, a = map(fields, (fw, health, status, safe))
    if (any(f.get(k) != v for k, v in (('CURRENT', 'A'), ('CONFIRMED', 'A'),
            ('PENDING', '-'), ('ATTEMPTS', '0'), ('ACTIVE', '0')))
            or h.get('READY') != '1' or h.get('MASK') != '0x000'
            or any(s.get(k) != v for k, v in (('MODE', 'IDLE'), ('BUSY', '0'), ('FLT', '0')))
            or any(a.get(k) != v for k, v in (('LATCHED', '0'), ('SD', '0'), ('MOE', '0')))):
        raise RuntimeError('A normal readiness/output-off gate failed')


def trace_config(line):
    row = fields(line)
    if any(row.get(k) != v for k, v in
           (('ENABLED', '1'), ('ROWS', '32'), ('FIRST_CAUSE', '1'), ('BYTES', '2000'))):
        raise RuntimeError('Exact startup trace configuration absent')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-single-compute-trial', action='store_true')
    parser.add_argument('--drive-12v-on', action='store_true')
    args = parser.parse_args()
    image = stage.pinned_image()
    if not args.allow_single_compute_trial:
        print('OFFLINE PASS: pinned A compute-only trial; no hardware access')
        return
    if not args.drive_12v_on:
        parser.error('Actual drive 12 V ON required for normal zero calibration')
    path, baseline = load_stage()
    run = 'startup-evidence-a-compute-' + str(time.time_ns())
    receipt = stage.OUTPUT / (run + '.json')
    final = stage.PRIVATE / (run + '-final.bin')
    row = dict(pass_=False, image_sha256=stage.SHA, stage=str(STAGED), steps=[],
        mode='COMPUTE_ONLY', trial_requests=0, motor_commands=0, app_programming=False,
        force_confirmation=False, fault_clearing=False, protection_edits=False,
        automatic_retry=False, trace_under_motor_start_verified=False, samples=[])
    port = uart = None
    attempted = False
    try:
        port = open_port()
        uart = Console(port)
        commands = activation_commands(stage.PRIVATE / (run + '-before.bin'), path)
        attempted = True  # Uncertain debug acknowledgement still requires output-off cleanup.
        row['trial_requests'] = 1
        debug(row, commands)
        print('ONE A bootloader trial; COMPUTATION ONLY, no START', flush=True)
        end = time.monotonic() + 50
        while time.monotonic() < end:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue  # Reads only across normal boot/confirmation reset.
            f = fields(fw)
            row['last_fw'] = fw
            if f.get('CURRENT') == 'B':
                raise RuntimeError('Bootloader selected fallback B; no automatic retry')
            if f.get('CURRENT') != 'A':
                continue
            try:
                status = uart.query('STATUS', .6)
                state = uart.query('MOTOR TEST STATUS', .6)
            except TimeoutError:
                continue
            row.update(last_status=status, last_state=state)
            if fields(status).get('FLT') != '0' or fields(state).get('STATE') == '4':
                row['startup_diagnostics'] = sample(uart)
                row['startup_filter'] = fields(uart.query('MOTOR TEST FILTER'))
                row['startup_zero'] = fields(uart.query('MOTOR TEST ZERO ROBUST'))
                raise RuntimeError('A startup fault; no START/retry')
            if f.get('CONFIRMED') == 'A' and f.get('PENDING') == '-' and f.get('ACTIVE') == '0':
                health, safe = uart.query('SELFTEST STATUS', .6), uart.query('ANALOG SAFE STATUS', .6)
                require_ready(fw, health, status, safe)
                row['confirmed_ready'] = dict(fw=fw, health=health, status=status, safe=safe)
                break
        else:
            raise TimeoutError('Normal A health confirmation absent; no forced confirmation')
        row['trace_config'] = trace_config(uart.query('MOTOR TEST STARTUP CONFIG'))
        # Several complete snapshots exercise actual background computation,
        # preserving diagnostic evidence before enforcing all timing gates.
        row['adaptive'] = fields(uart.query('MOTOR TEST FILTER'))
        row['robust_zero'] = fields(uart.query('MOTOR TEST ZERO ROBUST'))
        for _ in range(3):
            observed = sample(uart)
            row['samples'].append(observed)
            validate(observed, row['adaptive'], row['robust_zero'], expected_total_limit='OFF')
            uart.poll(.1)
        row['compute_pass'] = True
        print('COMPUTE PASS: zero, encoder, filter, <50us and startup CONFIG; no motor START', flush=True)
        row['stop_ack'] = uart.cleanup_command('STOP')
        row['off_ack'] = uart.cleanup_command('ANALOG SAFE')
        row['trace_after_off'] = fields(uart.query('MOTOR TEST STARTUP'))
        if any(row['trace_after_off'].get(k) != v for k, v in
               (('FROZEN', '1'), ('N', '0'), ('TOTAL', '0'), ('FAULT', '0'))):
            raise RuntimeError('Unexpected startup trace activity in no-START acceptance')
        row['pass_'] = True
    except BaseException as error:
        row['failure'] = str(error)
        print('COMPUTE FAILED: ' + str(error), flush=True)
    finally:
        if attempted:
            try:
                if port is None or not port.is_open:
                    port = open_port()
                    uart = Console(port)
                row['final_stop_ack'] = uart.cleanup_command('STOP')
                row['final_off_ack'] = uart.cleanup_command('ANALOG SAFE')
                row['final_trace_config'] = trace_config(uart.query('MOTOR TEST STARTUP CONFIG'))
                row['final_trace'] = uart.query('MOTOR TEST STARTUP')
                if fields(row['final_trace']).get('FAULT') == '1':
                    row['first_fault'] = uart.query('MOTOR TEST STARTUP FAULT')
            except BaseException as error:
                row['uart_cleanup_failure'] = str(error)
                row['pass_'] = False
            try:
                emergency_off(row, final)
                actual = final.read_bytes()
                if (len(actual) != 0x80000 or actual[:0x7E800] != baseline[:0x7E800]
                        or actual[0x7F800:] != baseline[0x7F800:]):
                    raise RuntimeError('APP/bootloader/private Flash changed')
                row['all_app_and_private_bytes_unchanged'] = True
                row['final_metadata'] = list(latest_meta(actual))
                row['final_sha256'] = hashlib.sha256(actual).hexdigest()
                if row.get('confirmed_ready'):
                    row['final_comparison'] = compare_flash(baseline, actual, image, 'A')
            except BaseException as error:
                row['pass_'] = False
                row['cleanup_failure'] = str(error)
                print('OUTPUT CLEANUP UNVERIFIED: switch drive 12 V OFF', flush=True)
        if uart:
            row['uart'] = uart.lines
        if port and port.is_open:
            port.close()
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('COMPUTE ACCEPTANCE ' + ('PASS' if row['pass_'] else 'FAIL'), flush=True)
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
