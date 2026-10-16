"""One pinned updated-original B trial and optional 20rpm/400ms motion check.

Never programs Flash or forces confirmation. Requires current physical test
readiness; stop/latch and finally halt with SD/PWM disabled even on failure.
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

import original_closed_loop_updated_stage as stage
from original_closed_loop_trial import Console, emergency_off, require_ready
from protected_irq_optimized_stage import open_port
from firmware_transfer_iap import fields

STAGED = stage.OUTPUT / 'original-updated-readback-1792049945637214400.json'
PROFILE = ('CONTROL PROFILE: ORIGINAL_UPDATED_20261015 TRIP_MA=4000 ZERO_DELTA=100 '
           'LOOP_US=50 SPEED_IQ_MA=400 DIRECT_IQ_MA=150 VOLTAGE_MV=800 '
           'FILTER=LEGACY_STEP_MEDIAN START=ORIGINAL QUALIFIED=0')


def mailbox(data):
    if len(data) != 200360 or hashlib.sha256(data).hexdigest() != stage.SHA:
        raise RuntimeError('Pinned updated-original B only')
    body = struct.pack('<7I', 0x584F424D, 1, 2, 1, 2, len(data), zlib.crc32(data))
    return struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))


def load_baseline():
    previous = json.loads(STAGED.read_text('utf-8'))
    if (previous.get('pass_') is not True or previous.get('image_sha256') != stage.SHA
            or previous.get('activation') is not False or previous.get('motor_commands') != 0
            or previous.get('metadata_unchanged') is not True
            or previous.get('all_bytes_outside_b_unchanged') is not True
            or previous.get('cpu_halted') is not True):
        raise RuntimeError('Exact independent successful readback required')
    path = Path(previous['readback_backup']).resolve()
    if path.parent != stage.PRIVATE.resolve():
        raise RuntimeError('Private baseline path mismatch')
    raw = path.read_bytes()
    if stage.validate_baseline(raw)[5] != 540:
        raise RuntimeError('Exact confirmed A540 required')
    stage.compare_flash(raw, raw, stage.pinned_image(), 'B', staged=True)
    return path, raw


def motion_result_ok(code, output):
    if code or any(text in output for text in ('SAFETY WARNING', ' failed:', 'Fault during motion')):
        raise RuntimeError('Short START/STOP or cleanup failed; no retry')
    if 'IN_MOTION ' not in output or 'Position change:' not in output:
        raise RuntimeError('Motion telemetry missing; not a closed-loop acceptance')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-single-trial', action='store_true')
    parser.add_argument('--allow-one-20rpm-400ms', action='store_true')
    parser.add_argument('--physical-test-ready', action='store_true')
    args = parser.parse_args()
    image = stage.pinned_image()
    words = mailbox(image)
    if not args.execute_single_trial:
        print('OFFLINE PASS: pinned updated-original B; no hardware access')
        return
    if not args.physical_test_ready:
        parser.error('Powered no-load fixed motor, wiring and immediate power-off readiness required')
    baseline_path, baseline = load_baseline()
    run = 'original-updated-trial-' + str(time.time_ns())
    receipt = stage.OUTPUT / (run + '.json')
    live = stage.PRIVATE / (run + '-before.bin')
    final = stage.PRIVATE / (run + '-final.bin')
    row = dict(pass_=False, image_sha256=stage.SHA, stage_readback=str(STAGED), steps=[],
               trial_requests=0, start_stop_invocations=0, force_confirmation=False,
               fault_clearing=False, automatic_activation_retry=False, flash_programming=False)
    port = uart = None
    activated = False
    try:
        port = open_port()
        uart = Console(port)
        commands = ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU no longer halted"}',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Output not off"}',
            f'dump_image {{{live.as_posix()}}} 0x08000000 0x80000',
            'proc task_readbin {path} {set handle [open $path rb]; set contents [read $handle]; close $handle; return $contents}',
            f'if {{[task_readbin {{{live.as_posix()}}}] ne [task_readbin {{{baseline_path.as_posix()}}}]}} {{error "Staged Flash changed"}}',
            'reset halt',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not reset halted"}',
            'mww 0x2001FFC0 0']
        commands += [f'mww {0x2001FFC0 + index * 4:#x} {words[index]:#x}' for index in range(1, 8)]
        commands += [f'mww 0x2001FFC0 {words[0]:#x}', 'reset run', 'shutdown']
        activated = True
        row['trial_requests'] = 1  # At most one attempt, including uncertain debug ACK.
        stage.debug(row, commands)
        print('ONE START_TRIAL: updated-original B; no motor START yet', flush=True)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            f = fields(fw)
            if f.get('CURRENT') == 'A' and f.get('PENDING') == '-':
                raise RuntimeError('Rejected/rolled back to A; no START')
            if f.get('CURRENT') != 'B':
                continue
            status = uart.query('STATUS', .6)
            if fields(status).get('FLT') != '0':
                row['fault_status'] = status
                raise RuntimeError('Updated B startup fault; no START')
            if f.get('CONFIRMED') == 'B' and f.get('PENDING') == '-':
                health = uart.query('SELFTEST STATUS', .6)
                safe = uart.query('ANALOG SAFE STATUS', .6)
                require_ready(fw, health, status, safe)
                if not any(PROFILE in line for line in uart.lines):
                    raise RuntimeError('Runtime 4A/100 profile not observed; no START')
                row['ready'] = dict(fw=fw, health=health, status=status, safe=safe)
                break
        else:
            raise TimeoutError('No normal B confirmation; no START or retry')
        print('BOOT PASS: runtime profile 4A/100 verified; calibration/selftest ready', flush=True)
        if args.allow_one_20rpm_400ms:
            port.close()
            row['start_stop_invocations'] = 1
            result = subprocess.run([sys.executable, '-u', str(stage.ROOT / 'tools/motor_motion_smoke.py'),
                '--execute', '--expected-slot', 'B', '--target-rpm', '20'],
                capture_output=True, text=True, errors='replace', timeout=25)
            output = result.stdout + result.stderr
            row['motion_result'] = dict(code=result.returncode, output=output)
            print(output, flush=True)
            motion_result_ok(result.returncode, output)
            row['short_test_completed'] = True
        row['pass_'] = True
    except BaseException as error:
        row['failure'] = str(error)
        print('TRIAL FAILED: ' + str(error), flush=True)
    finally:
        if activated:
            try:
                if port is None or not port.is_open:
                    port = open_port()
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
                    raise RuntimeError('Application/private bytes changed during trial')
                row['all_app_and_private_bytes_unchanged'] = True
                row['final_metadata'] = list(stage.latest_meta(actual))
                if row.get('ready'):
                    row['protected_regions'] = stage.compare_flash(baseline, actual, image, 'B')
                print('FINAL SAFE: CPU halted; SD/PWM OFF; no further reset/start', flush=True)
            except BaseException as error:
                row['cleanup_failure'] = str(error)
                row['pass_'] = False
                print('SWITCH OFF DRIVE 12 V: final off/readback proof failed', flush=True)
        if uart:
            row['uart'] = uart.lines
        if port is not None and port.is_open:
            port.close()
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(('PASS' if row['pass_'] else 'FAIL') + ': short test only, not torque qualification')
        print('Evidence: ' + str(receipt))
    if not row['pass_']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
