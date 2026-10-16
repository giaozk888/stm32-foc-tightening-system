"""One exact latest-B trial, then one original START/STOP 20rpm/400ms test.

No Flash programming, force confirmation, fault clear, protection edits, or
automatic activation/motion retry. Normal boot health and all preflight gates
must pass before the existing original-FSM smoke runner may send START.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import zlib

import latest_original_fsm_stage as stage
import protected_closed_loop_acceptance as shared
from protected_irq_timing_acceptance import TimingConsole, adc_timing
from protected_irq_priority_fix_acceptance import validate_encoder
from protected_fast_math_acceptance import validate_cost
from protected_pair_fast_acceptance import validate_late
from protected_compact_closed_loop_acceptance import sample
from original_closed_loop_trial import emergency_off, require_ready
from original_closed_loop_updated_trial import motion_result_ok
from protected_irq_optimized_stage import open_port
from firmware_transfer_iap import fields

STAGED = stage.OUTPUT / 'latest-original-stage-1792053661005666800.json'


class Console(TimingConsole):
    READ = TimingConsole.READ | frozenset(('SELFTEST STATUS', 'MOTOR TEST PROFILE',
        'MOTOR TEST RAM', 'MOTOR TEST COMPACT', 'MOTOR TEST FILTER', 'MOTOR TEST ZERO ROBUST'))

    def query(self, text, timeout=2):
        if text not in self.READ and text != 'ANALOG SAFE':
            raise ValueError('Acceptance console permits read/off only; START uses original runner')
        return shared.Console.query(self, text, timeout)

    def cleanup_command(self, text, timeout=.8):
        if text not in ('STOP', 'ANALOG SAFE'):
            raise ValueError('Stop/off only')
        self.request += 1
        request = self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = self.read_line(.02)
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '):
                    raise RuntimeError(line)
                return line
        raise TimeoutError('Cleanup ACK absent: ' + text)


def validate(row, adaptive, robust, ready=True, *, expected_total_limit='20'):
    if expected_total_limit not in ('20', 'OFF'):
        raise ValueError('Unknown explicit zero-total policy')
    def line(key):
        return 'OK ' + ' '.join(f'{k}={v}' for k, v in row[key].items())
    shared.protected_state(line('state'), ready=ready)
    shared.timing(line('timing'))
    shared.protection(line('protection'))
    adc_timing(line('adc'))
    validate_encoder(row)
    validate_cost(row)
    validate_late(row)
    expected = dict(NAME='LATEST_ORIGINAL_FSM', HARD_OFF='0', ADAPT='1', FSM='ORIGINAL',
                    ZERO='BOUNDED', LOCAL='1', RPM='20', LEASE_US='400000', QUALIFIED='0')
    if any(row['profile'].get(k) != v for k, v in expected.items()):
        raise RuntimeError('Exact latest-backend/original-FSM profile absent')
    for key, wanted in (('ram', dict(ENABLED='1', HARD_OFF='0', DEADLINE_US='50')),
        ('compact', dict(ENABLED='1', HARD_OFF='0', FIXED_OPS='1', GUARD_US='25', DEADLINE_US='50')),
        ('zero', dict(STATE='3', REASON='0', N='4000'))):
        if any(row[key].get(k) != v for k, v in wanted.items()):
            raise RuntimeError('New profile gate failed: ' + key)
    if any(adaptive.get(k) != v for k, v in dict(ADAPT='1', HARD_OFF='0', DELAY_PAIRS='1').items()):
        raise RuntimeError('Adaptive filter identity missing')
    if any(robust.get(k) != v for k, v in dict(BLOCK='5', SEGMENT='500', MAX=expected_total_limit, HARD_OFF='0', FLAGS='0').items()):
        raise RuntimeError('Robust zero policy/quality mismatch')
    b = row['buffer']
    if b.get('STK_VALID') != '1' or int(b.get('FREE_B', '0')) < 256 or int(b.get('DONE', '0')) < 1:
        raise RuntimeError('Background worker stack/data evidence absent')
    if row['fault'].get('VALID') != '0' or fields(row['status']).get('FLT') != '0':
        raise RuntimeError('Feedback/control fault; no START or retry')


def load_stage():
    r = json.loads(STAGED.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('image_sha256') != stage.SHA
        or r.get('new_b_activation') is not False or r.get('motor_commands') != 0
        or r.get('metadata_unchanged_by_stage') is not True
        or r.get('all_bytes_outside_b_unchanged') is not True
        or r.get('cpu_reset_halted') is not True):
        raise RuntimeError('Exact successful latest B stage receipt required')
    path = Path(r['staged_backup']).resolve()
    if path.parent != stage.PRIVATE.resolve():
        raise RuntimeError('Private stage path mismatch')
    raw = path.read_bytes()
    stage.baseline(raw, (1, 0, 0, 543))
    if hashlib.sha256(raw).hexdigest() != r['staged_sha256']:
        raise RuntimeError('Stage capture hash mismatch')
    stage.compare_flash(raw, raw, stage.pinned_image(), 'B', staged=True)
    return path, raw


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-one-original-start-trial', action='store_true')
    p.add_argument('--drive-powered-motor-fixed', action='store_true')
    args = p.parse_args()
    image = stage.pinned_image()
    words = stage.mailbox(2, 1, 2, len(image), zlib.crc32(image))
    if not args.allow_one_original_start_trial:
        print('OFFLINE PASS: pinned latest B; normal trial then original START only; no hardware access')
        return
    if not args.drive_powered_motor_fixed:
        p.error('Actual 12V/0.5A, fixed no-load motor and existing wiring required')
    path, baseline = load_stage()
    run = 'latest-original-trial-' + str(time.time_ns())
    receipt = stage.OUTPUT / (run + '.json')
    final = stage.PRIVATE / (run + '-final.bin')
    row = dict(pass_=False, image_sha256=stage.SHA, stage=str(STAGED), steps=[],
        trial_requests=0, original_start_runner_invocations=0, force_confirmation=False,
        protection_edits=False, automatic_retry=False, torque_accuracy_verified=False)
    port = uart = None
    activated = False
    try:
        port = open_port()
        uart = Console(port)
        commands = ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU no longer halted"}',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Output not off"}',
            *stage.full_compare_commands(stage.PRIVATE / (run + '-before.bin'), path),
            'reset halt', *stage.write_mailbox(words), 'reset run', 'shutdown']
        row['trial_requests'] = 1
        activated = True  # Uncertain debug ACK still requires stop/halt cleanup.
        stage.debug(row, commands)
        print('ONE latest-B bootloader trial; no motor START yet', flush=True)
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue  # Only read across normal boot/confirmation reset.
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
                raise RuntimeError('Latest B startup fault; no START/retry')
            if f.get('CONFIRMED') == 'B' and f.get('PENDING') == '-' and f.get('ACTIVE') == '0':
                health = uart.query('SELFTEST STATUS', .6)
                safe = uart.query('ANALOG SAFE STATUS', .6)
                require_ready(fw, health, status, safe)
                row['confirmed_ready'] = dict(fw=fw, health=health, status=status, safe=safe)
                break
        else:
            raise TimeoutError('Normal B confirmation not observed; no START/retry')
        row['before_start'] = sample(uart)
        row['adaptive'] = fields(uart.query('MOTOR TEST FILTER'))
        row['robust_zero'] = fields(uart.query('MOTOR TEST ZERO ROBUST'))
        validate(row['before_start'], row['adaptive'], row['robust_zero'])
        print('READY PASS: latest adaptive backend, bounded zero, encoder, 50us; ORIGINAL START once', flush=True)
        port.close()
        row['original_start_runner_invocations'] = 1
        try:
            proc = subprocess.run([sys.executable, '-u', str(stage.ROOT / 'tools/motor_motion_smoke.py'),
                '--execute', '--expected-slot', 'B', '--target-rpm', '20'],
                capture_output=True, text=True, errors='replace', timeout=25)
        except subprocess.TimeoutExpired as error:
            row['motion_timeout_stdout'] = str(error.stdout)
            row['motion_timeout_stderr'] = str(error.stderr)
            raise
        output = proc.stdout + proc.stderr
        row['motion_result'] = dict(code=proc.returncode, output=output)
        print(output, flush=True)
        motion_result_ok(proc.returncode, output)
        port = open_port()
        uart = Console(port)
        row['after_stop'] = sample(uart)
        validate(row['after_stop'], row['adaptive'], row['robust_zero'], ready=False)
        if row['after_stop']['state'].get('USED') != '1':
            raise RuntimeError('Protected original-FSM admission not observed')
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
                    raise RuntimeError('Application/private bytes changed')
                row['all_app_and_private_bytes_unchanged'] = True
                row['final_metadata'] = list(stage.latest_meta(actual))
                if row.get('confirmed_ready'):
                    row['final_comparison'] = stage.compare_flash(baseline, actual, image, 'B')
            except BaseException as error:
                row['pass_'] = False
                row['cleanup_failure'] = str(error)
                print('OUTPUT CLEANUP UNVERIFIED: switch off drive 12V now', flush=True)
        if uart:
            row['uart'] = uart.lines
        if port and port.is_open:
            port.close()
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('SHORT ORIGINAL-FSM ' + ('PASS' if row['pass_'] else 'FAIL'), flush=True)
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
