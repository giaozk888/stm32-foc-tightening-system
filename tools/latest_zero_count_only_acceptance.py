"""One pinned count-only B trial; optional original START 20rpm/400ms, once.

Normal boot confirmation only. Never flash, force-confirm, clear a fault,
change protection thresholds, or retry motion/activation on failure.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import latest_zero_count_only_stage as profile
from latest_original_fsm_acceptance import Console, validate
from protected_compact_closed_loop_acceptance import sample
from protected_irq_optimized_stage import open_port
from original_closed_loop_trial import emergency_off, require_ready
from original_closed_loop_updated_trial import motion_result_ok
from firmware_transfer_iap import fields

STAGED = profile.OUTPUT / 'latest-count-only-stage-1792054737463119300.json'
CONFIRMED_BASELINE = profile.OUTPUT / 'latest-count-only-trial-1792054959589196800.json'


def load_confirmed_baseline():
    """Exact previously captured B549, with no prior motor START, not a reflash."""
    r = json.loads(CONFIRMED_BASELINE.read_text('utf-8'))
    path = Path(r['final_backup']).resolve()
    if (path.parent != profile.PRIVATE.resolve() or r.get('image_sha256') != profile.SHA
        or r.get('final_outputs_off') is not True or r.get('final_cpu_halted') is not True
        or r.get('all_app_and_private_bytes_unchanged') is not True
        or r.get('original_start_runner_invocations') != 0
        or r.get('failure') != 'Count-only B startup fault; no START/retry'):
        raise RuntimeError('Exact stopped pre-START count-only B receipt required')
    raw = path.read_bytes()
    if len(raw) != 0x80000 or profile.shared.latest_meta(raw)[2:6] != (2, 0, 0, 549):
        raise RuntimeError('Exact confirmed B549 metadata required')
    image = profile.pinned_image()
    if (raw[0x40000:0x40000 + len(image)] != image
        or hashlib.sha256(raw[0x8000:0x8000 + 207972]).hexdigest() != profile.shared.A_SHA):
        raise RuntimeError('Pinned B or preserved A mismatch')
    return path, raw


def motion_observation(output):
    """Measured movement and actual FSM activity, not only a queued ACK."""
    change = re.search(r'Position change: ([+-]?[0-9.]+) deg', output)
    lines = [line for line in output.splitlines() if line.startswith('IN_MOTION ')]
    if not change or not any(fields(line).get('BUSY') == '1' for line in lines):
        raise RuntimeError('No observed original-FSM busy phase/position feedback')
    delta = float(change[1])
    if abs(delta) < 1.0:
        raise RuntimeError('Less than 1 degree measured movement; motor response not demonstrated')
    return dict(delta_deg=delta, observed_stages=sorted({fields(line).get('STAGE', '?') for line in lines}),
                in_motion_status=lines, steady_speed_qualified=False, torque_qualified=False)


def load_stage():
    r = json.loads(STAGED.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('image_sha256') != profile.SHA
        or r.get('new_b_activation') is not False or r.get('motor_commands') != 0
        or r.get('all_bytes_outside_b_unchanged') is not True
        or r.get('metadata_unchanged_by_stage') is not True
        or r.get('cpu_reset_halted') is not True or r.get('generation') != 546):
        raise RuntimeError('Exact successful count-only staging required')
    path = Path(r['staged_backup']).resolve()
    if path.parent != profile.PRIVATE.resolve():
        raise RuntimeError('Private stage path mismatch')
    raw = path.read_bytes()
    profile.shared.baseline(raw, (1, 0, 0, 546))
    if hashlib.sha256(raw).hexdigest() != r['staged_sha256']:
        raise RuntimeError('Stage backup changed')
    profile.shared.compare_flash(raw, raw, profile.pinned_image(), 'B', staged=True)
    return path, raw


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-single-count-only-trial', action='store_true')
    p.add_argument('--retest-confirmed-b', action='store_true',
                   help='New user-requested acceptance: one reset of exact confirmed B549, no trial mailbox')
    p.add_argument('--drive-powered-motor-fixed', action='store_true')
    p.add_argument('--allow-original-start-20rpm-400ms', action='store_true')
    args = p.parse_args()
    image, words = profile.pinned_image(), profile.trial_words()
    if args.allow_single_count_only_trial and args.retest_confirmed_b:
        p.error('Choose trial OR one confirmed-B reset, never both')
    if not (args.allow_single_count_only_trial or args.retest_confirmed_b):
        print('OFFLINE PASS: pinned count-only image; no hardware access')
        return
    if not args.drive_powered_motor_fixed:
        p.error('Actual 12V/0.5A, fixed no-load motor and existing wiring required')
    path, baseline = load_confirmed_baseline() if args.retest_confirmed_b else load_stage()
    run = 'latest-count-only-trial-' + str(time.time_ns())
    receipt = profile.OUTPUT / (run + '.json')
    final = profile.PRIVATE / (run + '-final.bin')
    row = dict(pass_=False, image_sha256=profile.SHA, stage=str(STAGED), steps=[],
        zero_total_policy='COUNT_ONLY', trial_requests=0, original_start_runner_invocations=0,
        force_confirmation=False, protection_edits=False, fault_clearing=False,
        automatic_retry=False, torque_accuracy_verified=False,
        confirmed_b_retest=bool(args.retest_confirmed_b), reset_requests=0)
    port = uart = None
    activated = False
    try:
        port = open_port()
        uart = Console(port)
        commands = ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
            ('if {[mrw 0xE000ED08] != 0x08040000} {error "Not confirmed B"}' if args.retest_confirmed_b else
             'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not bootloader"}'),
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Outputs not off"}',
            *profile.shared.full_compare_commands(profile.PRIVATE / (run + '-before.bin'), path)]
        if args.retest_confirmed_b:
            commands += ['reset run', 'shutdown']
            row['reset_requests'] = 1
            row['baseline_receipt'] = str(CONFIRMED_BASELINE)
        else:
            commands += ['reset halt', *profile.shared.write_mailbox(words), 'reset run', 'shutdown']
            row['trial_requests'] = 1
        activated = True
        profile.shared.debug(row, commands)
        print('ONE count-only B ' + ('confirmed reset' if args.retest_confirmed_b else 'trial') + '; NO motor START yet', flush=True)
        end = time.monotonic() + 50
        while time.monotonic() < end:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            f = fields(fw)
            if f.get('CURRENT') == 'A':
                raise RuntimeError('Bootloader selected fallback A; no START/retry')
            if f.get('CURRENT') != 'B':
                continue
            row['last_fw'] = fw
            try:
                status = uart.query('STATUS', .6)
                state = uart.query('MOTOR TEST STATUS', .6)
            except TimeoutError:
                continue
            row.update(last_status=status, last_state=state)
            if fields(status).get('FLT') != '0' or fields(state).get('STATE') == '4':
                row['startup_diagnostics'] = sample(uart)
                row['startup_filter'] = fields(uart.query('MOTOR TEST FILTER'))
                row['startup_robust_zero'] = fields(uart.query('MOTOR TEST ZERO ROBUST'))
                raise RuntimeError('Count-only B startup fault; no START/retry')
            if f.get('CONFIRMED') == 'B' and f.get('PENDING') == '-' and f.get('ACTIVE') == '0':
                health, safe = uart.query('SELFTEST STATUS'), uart.query('ANALOG SAFE STATUS')
                require_ready(fw, health, status, safe)
                row['confirmed_ready'] = dict(fw=fw, health=health, status=status, safe=safe)
                break
        else:
            raise TimeoutError('Normal health confirmation absent; no START/retry')
        row['before_start'] = sample(uart)
        row['adaptive'] = fields(uart.query('MOTOR TEST FILTER'))
        row['robust_zero'] = fields(uart.query('MOTOR TEST ZERO ROBUST'))
        validate(row['before_start'], row['adaptive'], row['robust_zero'], expected_total_limit='OFF')
        if args.retest_confirmed_b:
            row['stability_samples'] = []
            # Two complete, independently read snapshots before any motion.
            for _ in range(2):
                uart.poll(.05)
                observed = sample(uart)
                row['stability_samples'].append(observed)
                validate(observed, row['adaptive'], row['robust_zero'], expected_total_limit='OFF')
        row['zero_and_compute_pass'] = True
        print('COUNT-ONLY ZERO + COMPUTE PASS: MAX=OFF, full window, encoder and <50us gates', flush=True)
        if args.allow_original_start_20rpm_400ms:
            port.close()
            row['original_start_runner_invocations'] = 1
            try:
                proc = subprocess.run([sys.executable, '-u', str(profile.shared.ROOT / 'tools/motor_motion_smoke.py'),
                    '--execute', '--expected-slot', 'B', '--target-rpm', '20'],
                    capture_output=True, text=True, errors='replace', timeout=25)
            except subprocess.TimeoutExpired as error:
                row['motion_timeout_stdout'] = str(error.stdout)
                row['motion_timeout_stderr'] = str(error.stderr)
                raise
            output = proc.stdout + proc.stderr
            row['motion_result'] = dict(code=proc.returncode, output=output)
            print(output, flush=True)
            row['boot_uart'] = uart.lines
            port = open_port()
            uart = Console(port)
            row['after_stop'] = sample(uart)
            row['after_stop_filter'] = fields(uart.query('MOTOR TEST FILTER'))
            row['after_stop_robust_zero'] = fields(uart.query('MOTOR TEST ZERO ROBUST'))
            motion_result_ok(proc.returncode, output)
            row['motion_observation'] = motion_observation(output)
            validate(row['after_stop'], row['adaptive'], row['robust_zero'], ready=False, expected_total_limit='OFF')
            if row['after_stop']['state'].get('USED') != '1':
                raise RuntimeError('Original-FSM admission not observed')
        row['pass_'] = True
    except BaseException as error:
        row['failure'] = str(error)
        print('TRIAL FAILED: ' + str(error), flush=True)
    finally:
        if activated:
            try:
                if port is None or not port.is_open:
                    port = open_port()
                    if uart:
                        row['boot_uart'] = uart.lines
                    uart = Console(port)
                row['stop_ack'] = uart.cleanup_command('STOP')
                row['off_ack'] = uart.cleanup_command('ANALOG SAFE')
            except BaseException as error:
                row['uart_cleanup_failure'] = str(error)
            try:
                emergency_off(row, final)
                actual = final.read_bytes()
                if (len(actual) != 0x80000 or actual[:0x7E800] != baseline[:0x7E800]
                    or actual[0x7F800:] != baseline[0x7F800:]):
                    raise RuntimeError('App/private Flash changed')
                row['all_app_and_private_bytes_unchanged'] = True
                row['final_metadata'] = list(profile.shared.latest_meta(actual))
                if args.retest_confirmed_b:
                    if actual != baseline:
                        raise RuntimeError('Confirmed-B retest changed Flash/metadata')
                    row['all_flash_unchanged'] = True
                elif row.get('confirmed_ready'):
                    row['final_comparison'] = profile.shared.compare_flash(baseline, actual, image, 'B')
            except BaseException as error:
                row['pass_'] = False
                row['cleanup_failure'] = str(error)
                print('OUTPUT CLEANUP UNVERIFIED: switch drive 12V OFF now', flush=True)
        if uart:
            row['uart'] = uart.lines
        if port and port.is_open:
            port.close()
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('COUNT-ONLY TRIAL ' + ('PASS' if row['pass_'] else 'FAIL'), flush=True)
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
