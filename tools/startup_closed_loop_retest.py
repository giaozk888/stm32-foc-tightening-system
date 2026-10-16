"""A558 retained; exact protected startup-evidence B, one original START/STOP.

Default offline. OFF staging and ON trial are separate explicit phases.
No protection edits, forced confirmation, fault clear, SAVE or automatic retry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import zlib

import foc_repair_window_board_test as previous
import foc_startup_evidence_acceptance as evidence
from latest_original_fsm_acceptance import validate
from latest_zero_count_only_acceptance import motion_observation
from original_closed_loop_trial import require_ready
from original_closed_loop_updated_trial import motion_result_ok
from protected_compact_closed_loop_acceptance import sample

base = previous.base
OUTPUT, PRIVATE = base.OUTPUT, base.PRIVATE
PRIOR = OUTPUT / 'repair-window-trial-1792065115767450600.json'
BASELINE_SHA = '71a1d5e86bce8611ef12495f14c7cdeb901c3fa63cf07abb69eebe3abf13e1ee'
META = (1112493908, 3, 1, 0, 0, 558, 209820, 2832842604,
        208564, 4225420029, 0, 4128096433)
IMAGE = base.old.ROOT / 'foc2_app_b/build/LatestOriginalStartupEvidence/foc2.bin'
SHA = '2450f5a6da36c0698690aa2353fd1f76758e4b7401453fb7f361cfab1e72c61b'
SIZE = 210116
PREFIX = 'startup-closed-loop-'


def pinned_image():
    data = IMAGE.read_bytes()
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA or base.image_info(data)[0] != 'B':
        raise ValueError('Exact protected startup-evidence B required')
    for identity in (b'STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1',
            b'NAME=LATEST_ORIGINAL_FSM', b'MAX=OFF SEG_MAX=OFF',
            b'RPM=20 LEASE_US=400000 QUALIFIED=0', b'ADAPT=1 HARD_OFF=0'):
        if identity not in data:
            raise ValueError('Protected original-START candidate identity missing')
    return data


def load_before():
    row = json.loads(PRIOR.read_text('utf-8'))
    path = Path(row['final_backup']).resolve()
    if (path.parent != PRIVATE.resolve() or row.get('final_sha256') != BASELINE_SHA
            or row.get('image_sha256') != previous.SHA or row.get('motor_commands') != 0
            or row.get('trial_requests') != 1 or row.get('pass_') is not False
            or tuple(row.get('final_metadata', ())) != META
            or any(row.get(k) is not True for k in ('final_outputs_off', 'final_cpu_halted',
                                                   'all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact halted confirmed A558 receipt required')
    raw = path.read_bytes()
    if (len(raw) != 0x80000 or hashlib.sha256(raw).hexdigest() != BASELINE_SHA
            or base.latest_meta(raw) != META
            or raw[0x8000:0x8000 + previous.SIZE] != previous.pinned_image()):
        raise ValueError('A558 baseline capture changed')
    return path, raw


def stage_commands(live, baseline, staged):
    return [*base.output_gate(0x08008000), *base.full_compare_commands(live, baseline),
        'reset halt',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not bootloader"}',
        *base.off_commands(), f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08040000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000', *base.off_report(),
        'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}', 'halt', 'shutdown']


def verify_stage(before, actual, image):
    result = evidence.compare_flash(before, actual, image, 'B', staged=True)
    if before[:0x40000] != actual[:0x40000] or before[0x78000:] != actual[0x78000:]:
        raise ValueError('Bytes outside inactive B changed')
    if base.latest_meta(actual) != META:
        raise ValueError('Stage changed A558 metadata')
    return result


def stage(row, run, image):
    path, before = load_before()
    staged = PRIVATE / (run + '-staged.bin')
    row['hardware_attempted'] = True
    result = base.debug(row, stage_commands(PRIVATE / (run + '-before.bin'), path, staged))
    row['outputs'] = base.check_off(result, (0, 0x08000000))
    actual = staged.read_bytes()
    row['comparison'] = verify_stage(before, actual, image)
    row.update(pass_=True, staged_backup=str(staged), staged_sha256=hashlib.sha256(actual).hexdigest(),
        metadata_unchanged=True, all_bytes_outside_b_unchanged=True, cpu_reset_halted=True,
        final_cpu_halted=True, final_outputs_off=True, activation=False)
    print('STAGE PASS: exact protected B; A558/bootloader/private retained; NOT activated', flush=True)


def load_stage(path):
    path = path.resolve()
    if path.parent != OUTPUT.resolve() or not path.name.startswith(PREFIX + 'stage-'):
        raise ValueError('Exact new protected B stage receipt required')
    row = json.loads(path.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage'
            or row.get('image_sha256') != SHA or row.get('activation') is not False
            or row.get('original_start_runner_invocations') != 0
            or any(row.get(k) is not True for k in ('metadata_unchanged', 'all_bytes_outside_b_unchanged',
                                                   'cpu_reset_halted', 'final_outputs_off'))):
        raise ValueError('Exact unactivated protected B required')
    private = Path(row['staged_backup']).resolve()
    if private.parent != PRIVATE.resolve():
        raise ValueError('Private capture location mismatch')
    raw = private.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['staged_sha256']:
        raise ValueError('Stage capture changed')
    _, before = load_before()
    verify_stage(before, raw, pinned_image())
    return private, raw


def trial_words():
    image = pinned_image()
    body = struct.pack('<7I', 0x584F424D, 1, 2, 1, 2, len(image), zlib.crc32(image))
    return struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))


def activation_commands(live, baseline):
    gate = base.output_gate(0)
    gate[2] = 'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}'
    return [*gate, *base.full_compare_commands(live, baseline), 'reset halt',
            *base.write_mailbox(trial_words()), 'reset run', 'shutdown']


class Console(evidence.Console):
    READ = evidence.Console.READ | frozenset('MOTOR TEST STARTUP FRAME ' + str(i) for i in range(32))


def collect_trace(uart, row):
    row['trace_config'] = evidence.trace_config(uart.query('MOTOR TEST STARTUP CONFIG'))
    summary = row['startup_trace'] = base.fields(uart.query('MOTOR TEST STARTUP'))
    count = int(summary.get('N', '-1'))
    if summary.get('FROZEN') != '1' or not 0 <= count <= 32:
        raise ValueError('No bounded immutable startup evidence')
    if summary.get('FAULT') == '1':
        row['first_fault'] = base.fields(uart.query('MOTOR TEST STARTUP FAULT'))
    frames = row['startup_frames'] = []
    for i in range(count):
        frames.append(base.fields(uart.query('MOTOR TEST STARTUP FRAME ' + str(i))))
    again = base.fields(uart.query('MOTOR TEST STARTUP'))
    if again != summary:
        raise ValueError('Frozen startup evidence changed while reading')
    row['startup_capture_complete'] = True


def trial(row, run, image, stage_path):
    path, before = load_stage(stage_path)
    port = uart = None
    try:
        port = base.open_port()
        uart = Console(port)
        row.update(hardware_attempted=True, trial_requests=1)
        base.debug(row, activation_commands(PRIVATE / (run + '-before.bin'), path))
        print('ONE protected B trial; normal confirmation/preflight before original START', flush=True)
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            time.sleep(.1)
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            f = base.fields(fw)
            row['fw'] = fw
            if f.get('CURRENT') == 'A':
                raise ValueError('Fallback A selected; no START/retry')
            if f.get('CURRENT') != 'B':
                continue
            try:
                status = uart.query('STATUS', .6)
                state = uart.query('MOTOR TEST STATUS', .6)
            except TimeoutError:
                continue
            row.update(last_status=status, last_state=state)
            if base.fields(status).get('FLT') != '0' or base.fields(state).get('STATE') == '4':
                row['startup_diagnostics'] = sample(uart)
                row['startup_zero'] = base.fields(uart.query('MOTOR TEST ZERO ROBUST'))
                raise ValueError('Protected B startup fault; no START/retry')
            if f.get('CONFIRMED') == 'B' and f.get('PENDING') == '-' and f.get('ACTIVE') == '0':
                health, safe = uart.query('SELFTEST STATUS'), uart.query('ANALOG SAFE STATUS')
                require_ready(fw, health, status, safe)
                row['confirmed_ready'] = dict(fw=fw, health=health, status=status, safe=safe)
                break
        else:
            raise TimeoutError('Normal B confirmation absent; no START/retry')
        row['before_start'] = sample(uart)
        row['adaptive'] = base.fields(uart.query('MOTOR TEST FILTER'))
        row['robust_zero'] = base.fields(uart.query('MOTOR TEST ZERO ROBUST'))
        validate(row['before_start'], row['adaptive'], row['robust_zero'], expected_total_limit='OFF')
        row['trace_config'] = evidence.trace_config(uart.query('MOTOR TEST STARTUP CONFIG'))
        row['zero_and_compute_pass'] = True
        print('PRESTART PASS: latest filter, original FSM, retained protection, START once', flush=True)
        port.close()
        row['boot_uart'] = uart.lines
        row['original_start_runner_invocations'] = 1
        try:
            process = subprocess.run([sys.executable, '-u', str(base.old.ROOT/'tools/motor_motion_smoke.py'),
                '--execute', '--expected-slot', 'B', '--target-rpm', '20'],
                capture_output=True, text=True, errors='replace', timeout=25)
        except subprocess.TimeoutExpired as error:
            row['motion_timeout_stdout'] = str(error.stdout)
            row['motion_timeout_stderr'] = str(error.stderr)
            raise
        output = process.stdout + process.stderr
        row['motion_result'] = dict(code=process.returncode, output=output)
        print(output, flush=True)
        port = base.open_port()
        uart = Console(port)
        row['after_stop'] = sample(uart)
        collect_trace(uart, row)
        motion_result_ok(process.returncode, output)
        row['motion_observation'] = motion_observation(output)
        validate(row['after_stop'], row['adaptive'], row['robust_zero'], ready=False, expected_total_limit='OFF')
        if row['after_stop']['state'].get('USED') != '1':
            raise ValueError('Original FSM admission not observed')
        row['pass_'] = True
    finally:
        try:
            if row.get('hardware_attempted'):
                try:
                    if port is None or not port.is_open:
                        port = base.open_port()
                        uart = Console(port)
                    row['stop_ack'] = uart.cleanup_command('STOP')
                    # Read after STOP freezes a successful cycle, before any reset.
                    if not row.get('startup_capture_complete'):
                        try:
                            collect_trace(uart, row)
                        except Exception as error:
                            row['trace_error'] = str(error)
                    row['off_ack'] = uart.cleanup_command('ANALOG SAFE')
                except Exception as error:
                    row['uart_cleanup_error'] = str(error)
                    row['pass_'] = False
                final = PRIVATE / (run + '-final.bin')
                base.emergency_off(row, final)
                actual = final.read_bytes()
                if (actual[:0x7E800] != before[:0x7E800] or actual[0x7F800:] != before[0x7F800:]
                        or len(actual) != 0x80000):
                    raise ValueError('APP/bootloader/private bytes changed during trial')
                meta = base.latest_meta(actual)
                if (meta[5] <= META[5] or meta[6:8] != META[6:8]
                        or meta[8:10] != (len(image), zlib.crc32(image))
                        or meta[2:5] not in ((1, 2, 1), (2, 0, 0))):
                    raise ValueError('Unexpected normal trial/confirmation metadata')
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
    modes.add_argument('--stage-b', action='store_true')
    modes.add_argument('--trial-from', type=Path)
    power = parser.add_mutually_exclusive_group()
    power.add_argument('--drive-12v-off', action='store_true')
    power.add_argument('--drive-powered-motor-fixed', action='store_true')
    args = parser.parse_args()
    image = pinned_image()
    if not args.stage_b and not args.trial_from:
        print('OFFLINE PASS: exact protected original-START B; no hardware/private access')
        return
    if (args.stage_b and not args.drive_12v_off) or (args.trial_from and not args.drive_powered_motor_fixed):
        parser.error('Actual physical state required for the selected phase')
    mode = 'stage' if args.stage_b else 'trial'
    run = PREFIX + mode + '-' + str(time.time_ns())
    row = dict(pass_=False, mode=mode, image_sha256=SHA, image_bytes=SIZE, steps=[],
        trial_requests=0, original_start_runner_invocations=0, automatic_retry=False,
        force_confirmation=False, direct_metadata_write=False, protection_edits=False,
        fault_clearing=False, torque_accuracy_verified=False, steady_speed_qualified=False,
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
