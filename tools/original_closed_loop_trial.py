"""One verified original-B boot trial and optional original START/STOP short test.

No Flash programming, forced confirmation, protection edits or activation retry.
Bootloader validates START_TRIAL; APP must pass normal health confirmation.
On failure, stop/latch safe or halt and force SD/PWM OFF through the debugger.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import zlib

import original_closed_loop_stage as stage
from firmware_transfer_iap import fields
from powered_boot_probe import ProbeUart, register_safe_line
from protected_irq_optimized_stage import Board, open_port
from tighten_synthetic_swd_recovery import OCD, SCRIPTS, SN, latest_meta
from zero_retest_deploy import compare_flash

RECEIPT = stage.OUTPUT / 'original-b-stage-1792047600921691400.json'


def mailbox(image):
    if len(image) != 199056 or hashlib.sha256(image).hexdigest() != stage.SHA:
        raise RuntimeError('Exact original B only')
    packet = struct.pack('<7I', 0x584F424D, 1, 2, 1, 2, len(image), zlib.crc32(image))
    return struct.unpack('<8I', packet + struct.pack('<I', zlib.crc32(packet)))


def require_halted_off(output, require_halt=True):
    registers = {int(a, 16): int(v, 16) for a, v in
                 re.findall(r'(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$', output)}
    register_safe_line(output)
    if (registers.get(0xE000ED08) not in (0, 0x08000000) or
        (require_halt and not registers.get(0xE000EDF0, 0) & 0x20000) or
        registers.get(0x40012C20) != 0 or registers.get(0x40012C44, 0xFFFF) & 0xC000):
        raise RuntimeError('Expected halted bootloader and disabled outputs')


def require_ready(fw, health, status, safe):
    f, h, s, a = map(fields, (fw, health, status, safe))
    if (any(f.get(k) != v for k, v in (('CURRENT', 'B'), ('CONFIRMED', 'B'),
            ('PENDING', '-'), ('ATTEMPTS', '0'), ('ACTIVE', '0'))) or
        h.get('READY') != '1' or h.get('MASK') != '0x000' or
        any(s.get(k) != v for k, v in (('MODE', 'IDLE'), ('BUSY', '0'), ('FLT', '0'))) or
        a.get('LATCHED') != '0'):
        raise RuntimeError('Original B normal readiness gate failed; no START')


class Console(ProbeUart):
    def __init__(self, port):
        super().__init__(port)
        self.lines = []

    def dispatch(self, line):
        if len(self.lines) < 10000:
            self.lines.append(line)
        # Capture other startup output privately; print relevant diagnostics only.
        if any(key in line for key in ('ZERO', 'FAILED', 'FAULT', 'ERROR', 'HardFault',
                                       ' OK FW ', ' OK SELFTEST ', ' OK STATUS ', ' OK ANALOG ')):
            super().dispatch(line)

    def cleanup_command(self, text, timeout=.8):
        if text not in ('STOP', 'ANALOG SAFE'):
            raise ValueError('Stop/disable only')
        self.request += 1
        request = self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(.02)
            if line is None:
                continue
            self.lines.append(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '):
                    raise RuntimeError(line)
                return line
        raise TimeoutError('Cleanup unacknowledged: ' + text)


def openocd(record, commands, timeout=18):
    result = subprocess.run([OCD, '-s', SCRIPTS, '-f', 'interface/stlink.cfg',
        '-f', 'target/stm32g4x.cfg', '-c',
        'gdb_port disabled; tcl_port disabled; telnet_port disabled; adapter serial ' + SN +
        '; adapter speed 1000; ' + '; '.join(commands)],
        capture_output=True, text=True, errors='replace', timeout=timeout)
    output = result.stdout + result.stderr
    record['steps'].append(dict(tool='OpenOCD', commands=commands, code=result.returncode, output=output))
    if result.returncode or 'Error:' in output:
        raise RuntimeError('Debug operation failed; no automatic activation retry')
    return output


def emergency_off(record, final_path=None):
    commands = ['init', 'halt', 'mmw 0x4002104C 0x4 0',
        'mww 0x48000818 0x00400000', 'mmw 0x48000800 0x1000 0x2000',
        'mmw 0x40021060 0x800 0', 'mww 0x40012C20 0',
        'mmw 0x40012C44 0 0xC000', 'mmw 0x40012C00 0 1',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Output off proof failed"}',
        'halt']
    if final_path is not None:
        # Keep the full capture inside this halted session. A subsequent
        # CubeProgrammer HOTPLUG capture can release the halt/debug watchdog
        # freeze and let an unconfirmed APP reset/rollback before inspection.
        commands += [f'dump_image {{{final_path.as_posix()}}} 0x08000000 0x80000']
    commands += ['halt', 'shutdown']
    openocd(record, commands)
    record.update(final_outputs_off=True, final_cpu_halted=True)
    if final_path is not None:
        record['final_backup'] = str(final_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-single-original-trial', action='store_true')
    parser.add_argument('--allow-one-20rpm-400ms-start-stop', action='store_true')
    parser.add_argument('--drive-powered-motor-fixed', action='store_true')
    args = parser.parse_args()
    image = stage.IMAGE.read_bytes()
    words = mailbox(image)
    if not (args.allow_single_original_trial and args.drive_powered_motor_fixed):
        print('OFFLINE PASS: exact original B; START_TRIAL requester=A target=B; NO hardware access')
        return
    previous = json.loads(RECEIPT.read_text('utf-8'))
    if not (previous.get('pass_') and previous.get('cpu_reset_halted') and
            previous.get('metadata_unchanged') and previous.get('image_sha256') == stage.SHA and
            previous.get('activation') is False):
        raise RuntimeError('Successful exact halted stage receipt required')
    baseline_path = Path(previous['staged_backup']).resolve()
    if baseline_path.parent != (stage.OUTPUT / 'private').resolve():
        raise RuntimeError('Capture path mismatch')
    baseline = baseline_path.read_bytes()
    run = 'original-b-trial-' + str(time.time_ns())
    output_path = stage.OUTPUT / (run + '.json')
    row = dict(pass_=False, image_sha256=stage.SHA, stage=str(RECEIPT), steps=[],
               trial_requests=0, motor_test_invocations=0, force_confirmation=False,
               fault_clearing=False, automatic_activation_retry=False)
    board = Board(row, run)
    port = uart = None
    activated = False
    try:
        actual = board.capture('before_trial')
        if actual != baseline or latest_meta(actual)[2:6] != (1, 0, 0, 536):
            raise RuntimeError('Exact staged Flash/A536 metadata changed')
        compare_flash(actual, actual, image, 'B', staged=True)
        registers = board.cli(*[item for address in (0xE000ED08, 0xE000EDF0, 0x48000814,
            0x40012C44, 0x40012C00, 0x40012C20) for item in ('-r32', hex(address), '4')])
        # CubeProgrammer HOTPLUG may release C_DEBUGEN on detach. Establish
        # and prove HALT in the exclusive OpenOCD session, not across tools.
        require_halted_off(registers, require_halt=False)
        row['debug_preparation'] = 'Controlled reset-halt after debugger handoff; no APP fault clear'
        port = open_port()
        uart = Console(port)
        commands = ['init', 'halt', 'reset halt',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not in staged bootloader"}',
            'mmw 0x4002104C 0x4 0', 'mww 0x48000818 0x00400000',
            'mmw 0x48000800 0x1000 0x2000', 'mmw 0x40021060 0x800 0',
            'mww 0x40012C20 0', 'mmw 0x40012C44 0 0xC000', 'mmw 0x40012C00 0 1',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Output off proof failed"}',
            f'verify_image {{{stage.IMAGE.as_posix()}}} 0x08040000 bin',
            'mww 0x2001FFC0 0']
        commands += [f'mww {0x2001FFC0 + i * 4:#x} {words[i]:#x}' for i in range(1, 8)]
        commands += [f'mww 0x2001FFC0 {words[0]:#x}', 'reset run', 'shutdown']
        activated = True  # An uncertain debug ACK never causes a repeated request.
        row['trial_requests'] = 1
        openocd(row, commands)
        print('One normal bootloader START_TRIAL requested; no START sent', flush=True)
        deadline = time.monotonic() + 40
        saw_b = False
        while time.monotonic() < deadline:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            f = fields(fw)
            saw_b = saw_b or f.get('CURRENT') == 'B'
            if f.get('CURRENT') == 'A' and f.get('PENDING') == '-':
                raise RuntimeError('Trial rejected or rolled back to A; no START')
            if f.get('CURRENT') != 'B':
                continue
            status = uart.query('STATUS', .6)
            if fields(status).get('FLT') != '0':
                row['fault_status'] = status
                raise RuntimeError('Original B fault during startup; no START')
            if f.get('CONFIRMED') == 'B' and f.get('PENDING') == '-':
                health = uart.query('SELFTEST STATUS', .6)
                safe = uart.query('ANALOG SAFE STATUS', .6)
                require_ready(fw, health, status, safe)
                row['ready'] = dict(fw=fw, health=health, status=status, safe=safe)
                break
        else:
            raise TimeoutError('No normal B confirmation within 40 seconds; no retry')
        row['confirmed_flash'] = compare_flash(baseline, board.capture('confirmed'), image, 'B')
        print('BOOT PASS: original B normally confirmed, calibration/selftest ready', flush=True)
        if args.allow_one_20rpm_400ms_start_stop:
            port.close()
            row['motor_test_invocations'] = 1
            result = subprocess.run([sys.executable, '-u', str(stage.ROOT / 'tools/motor_motion_smoke.py'),
                '--execute', '--expected-slot', 'B', '--target-rpm', '20'],
                capture_output=True, text=True, errors='replace', timeout=25)
            row['motion_result'] = dict(code=result.returncode, output=result.stdout + result.stderr)
            print(result.stdout + result.stderr, flush=True)
            if result.returncode:
                raise RuntimeError('Original START/STOP short test failed; never retry')
            row['short_test_pass'] = True
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
                safe = fields(uart.query('ANALOG SAFE STATUS', .8))
                row['final_safe'] = safe
                if any(safe.get(k) != v for k, v in (('LATCHED', '1'), ('SD', '0'), ('MOE', '0'), ('FOC', '0'))):
                    raise RuntimeError('Off latch unverified')
                row['final_fw'] = uart.query('FW STATUS', .8)
                row['final_status'] = uart.query('STATUS', .8)
                register_safe_line(board.cli(*[item for a in (0x48000814, 0x40012C44, 0x40012C00)
                                                   for item in ('-r32', hex(a), '4')]))
                row['final_outputs_off'] = True
            except BaseException as error:
                row['uart_cleanup_failure'] = str(error)
                row['pass_'] = False
                try:
                    emergency_off(row, stage.OUTPUT / 'private' / (run + '-halted-final.bin'))
                    print('DEBUG SAFE: CPU halted; SD/PWM OFF; no reset or restart', flush=True)
                except BaseException as failure:
                    row['cleanup_failure'] = str(failure)
                    print('SWITCH OFF DRIVE 12 V NOW: off proof unavailable', flush=True)
            if not row.get('final_cpu_halted'):
                try:
                    board.capture('final')
                except BaseException as error:
                    row['final_capture_failure'] = str(error)
        if uart:
            row['uart'] = uart.lines
        if port is not None and port.is_open:
            port.close()
        output_path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(('PASS' if row['pass_'] else 'FAIL') + ': original B test; not torque accuracy qualification', flush=True)
        print('Evidence: ' + str(output_path), flush=True)
    if not row['pass_']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
