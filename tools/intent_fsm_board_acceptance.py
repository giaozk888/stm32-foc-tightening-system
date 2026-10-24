"""Pinned FSM candidate: OFF stage, separate powered 20rpm/2s run, OFF restore.

No automatic retry, persistent recipe write, current increase or forced contact.
The host STOP window does not replace the unchanged 12s independent board lease.
Default invocation is files only; never accesses a device.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import torque450_150rpm_acceptance as support
from speed500_dynamic_acceptance import mailbox
from loaded_fsm_motion import RecordedBoard, check_profile

old = support.old
hw = support.hw
TMP = support.TMP
# Immutable A728 evidence: rebuilding a candidate must not change the ELF
# used to decode/restore this historical receipt. New board runs need new pins.
IMAGE = TMP / 'intent-fsm-a728-evidence/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = 'f010e5a63ce2e0cc7362b91809ac4bb5c2c53708c4be22ab6efe472e2169cda9'
ELF_SHA = '6594f451d10943761b2542dbd207e6ea0abeb00cf218a3c56a840f19e72b2b10'
BASE = TMP / 'torque450-150-restore-1792408962997353700-flash.bin'
BASE_SHA = '5d6a9e4ad0edf4248f5eab180d65e8f75b710421238f382deaa7da1538621a2e'


def image():
    data = IMAGE.read_bytes()
    commands = json.loads((IMAGE.parent / 'compile_commands.json').read_text('utf-8'))
    command = next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    support.require_baud(command)
    if (len(data) != 229220 or old.zero.digest(data) != SHA or
            old.zero.digest(ELF.read_bytes()) != ELF_SHA or hw.image_info(data)[0] != 'A' or
            command.count('-DFOC_INTENT_FSM_CANDIDATE=1') != 1):
        raise ValueError('Exact tested FSM A BIN/ELF required')
    for marker in (b'INTENT_FSM_CANDIDATE; manual START only', b'FSM_STATE=',
                   b'METHOD=TWO_SAMPLE', b'TRIP_MA=4000', b'RPM=20 LEASE_US=12000000'):
        if marker not in data:
            raise ValueError('Candidate identity/protection marker absent')
    return data


def baseline():
    raw = BASE.read_bytes()
    meta = old.zero.latest_meta(raw)
    if (len(raw) != 0x80000 or old.zero.digest(raw) != BASE_SHA or
            meta[2:6] != (2, 0, 0, 725) or
            meta[6:10] != (222532, 2889731024, 227964, 627317606) or
            zlib.crc32(raw[0x40000:0x40000 + meta[8]]) != meta[9]):
        raise ValueError('Exact preserved B725 baseline required')
    return raw


def stage(row, name, data):
    if row.get('physical_power_off') is not True:
        raise ValueError('Fresh drive OFF required')
    before = baseline()
    dest = TMP / (name + '-staged.bin')
    row['hardware_attempted'] = True
    old.prior.checkpoint(row, 'inactive_A_program_intent')
    output = hw.debug(row, [*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B725"}',
        *hw.full_compare_commands(TMP / (name + '-before.bin'), BASE),
        'reset halt', *hw.off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{dest.as_posix()}}} 0x08000000 0x80000',
        *hw.off_report(), 'halt', 'shutdown'])
    raw = dest.read_bytes()
    old.zero.validate_staged(raw, before, data)
    hw.debug(row, [*old.zero.off_gate(),
        *hw.full_compare_commands(TMP / (name + '-independent.bin'), dest),
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin', 'halt', 'shutdown'])
    row.update(pass_=True, staged_capture=str(dest), staged_sha256=old.zero.digest(raw),
        outputs=hw.check_off(output, (0, 0x08000000)), metadata=list(old.zero.latest_meta(raw)),
        activation=False, motor_commands=0, b_boot_private_metadata_unchanged=True,
        independent_readback_pass=True, final_cpu_halted=True, final_outputs_off=True)


def staged_input(path, data):
    r = json.loads(path.read_text('utf-8'))
    capture = Path(r.get('staged_capture', '')).resolve()
    if (path.resolve().parent != TMP.resolve() or capture.parent != TMP.resolve() or
            r.get('mode') != 'stage' or r.get('pass_') is not True or
            r.get('image_sha256') != SHA or r.get('elf_sha256') != ELF_SHA or
            r.get('physical_power_off') is not True or
            r.get('independent_readback_pass') is not True):
        raise ValueError('Exact successful OFF stage required')
    raw = capture.read_bytes()
    if old.zero.digest(raw) != r.get('staged_sha256'):
        raise ValueError('Stage capture changed')
    old.zero.validate_staged(raw, baseline(), data)
    return capture, raw


def execute(row, name, path, data):
    if row.get('powered_no_alarm') is not True:
        raise ValueError('Fresh powered no-alarm conditions required')
    staged, before = staged_input(path, data)
    port = support.open_port()
    uart = old.prior.JournalConsole(port, row)
    try:
        row['hardware_attempted'] = True
        old.prior.checkpoint(row, 'trial_intent_no_motion')
        hw.debug(row, [*old.zero.off_gate(),
            *hw.full_compare_commands(TMP / (name + '-before.bin'), staged),
            'reset halt', *hw.off_commands(),
            *hw.write_mailbox(mailbox(2, 2, 1, len(data), zlib.crc32(data))),
            'reset run', 'shutdown'])
        old.prior.wait_health_confirmation(uart, row, hw.fields)
        if not any('INTENT_FSM_CANDIDATE; manual START only' in line for line in uart.lines):
            raise RuntimeError('Actual boot candidate marker absent; no START')
        row['zero'] = old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        check_profile(hw.fields(uart.query('MOTOR TEST PROFILE')), 'SB3')
        old.prior.wait_timing(uart, row)
        row['preflight_pass'] = True
        old.prior.checkpoint(row, 'preflight_pass')
        port.close()
        board = RecordedBoard('COM5', row)
        try:
            old.prior.motion(board, row, expected_speed_ctrl='SB3')
        finally:
            board.close()
    finally:
        if port.is_open:
            # Even a failed startup never falls through into a START retry.
            try:
                row['stop_ack'] = uart.query('STOP', .6)
                row['safe_ack'] = uart.query('ANALOG SAFE', .6)
            except Exception as error:
                row['stop_error'] = str(error)
            port.close()
        if row.get('hardware_attempted'):
            old.capture_stopped(row, name, before, elf=ELF)
    snap = row.get('snapshot')
    if (not snap or snap['first_fault']['valid'] or snap['timing']['deadline_miss'] or
            snap['timing']['actual_late_count']):
        raise RuntimeError('Postflight protection/timing failure')
    row['pass_'] = bool(row.get('motion_pass'))


def restore(row, name, path, data):
    if row.get('physical_power_off') is not True:
        raise ValueError('Fresh drive OFF required')
    r = json.loads(path.read_text('utf-8'))
    expected = Path(r.get('final_capture', '')).resolve()
    if (path.resolve().parent != TMP.resolve() or expected.parent != TMP.resolve() or
            r.get('mode') != 'run' or r.get('image_sha256') != SHA or
            r.get('elf_sha256') != ELF_SHA or any(r.get(k) is not True for k in
            ('final_cpu_halted', 'final_outputs_off', 'all_app_private_unchanged'))):
        raise ValueError('Exact stopped candidate receipt required')
    before = expected.read_bytes()
    base = baseline()
    meta = old.zero.latest_meta(before)
    if (old.zero.digest(before) != r.get('final_sha256') or
            before[0x8000:0x8000 + len(data)] != data or meta[2:5] != (1, 0, 0) or
            meta[6:8] != (len(data), zlib.crc32(data)) or before[:0x8000] != base[:0x8000] or
            before[0x40000:0x7e800] != base[0x40000:0x7e800] or
            before[0x7f800:] != base[0x7f800:]):
        raise ValueError('Stopped A / preserved B identity mismatch')
    entry = struct.unpack_from('<I', before, 0x40004)[0] & ~1
    if not 0x08040000 <= entry < 0x08040000 + meta[8]:
        raise ValueError('B entry invalid')
    final = TMP / (name + '-flash.bin')
    row['hardware_attempted'] = True
    old.prior.checkpoint(row, 'restore_B_intent_no_motion')
    output = hw.debug(row, [*old.zero.off_gate(),
        *hw.full_compare_commands(TMP / (name + '-before.bin'), expected),
        'reset halt', f'bp {entry:#x} 2 hw', *hw.write_mailbox(mailbox(3, 1, 2)),
        'reset run', 'wait_halt 25000', f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B application"}}',
        *hw.off_commands(), *hw.off_report(),
        f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000', 'halt', 'shutdown'])
    raw = final.read_bytes()
    updated = old.zero.latest_meta(raw)
    if (raw[:0x7e800] != before[:0x7e800] or raw[0x7f800:] != before[0x7f800:] or
            updated[2:5] != (2, 0, 0) or updated[5] <= meta[5] or
            updated[6:10] != meta[6:10]):
        raise RuntimeError('B restoration/preservation failed')
    row.update(pass_=True, final_capture=str(final), final_sha256=old.zero.digest(raw),
        metadata=list(updated), outputs=hw.check_off(output, (0x08040000,)),
        all_app_private_unchanged=True, b_application_not_run=True,
        final_cpu_halted=True, final_outputs_off=True, motor_commands=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--stage-off', action='store_true')
    mode.add_argument('--execute-powered', type=Path)
    mode.add_argument('--restore-b-drive-off', type=Path)
    parser.add_argument('--drive-off-connected-fixed', action='store_true')
    parser.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready', action='store_true')
    args = parser.parse_args()
    if (args.stage_off or args.restore_b_drive_off) and not args.drive_off_connected_fixed:
        parser.error('Fresh drive OFF, connected fixed motor required')
    if args.execute_powered and not args.drive_on_no_alarm_fixed_05a_emergency_off_ready:
        parser.error('Fresh powered/no-alarm, fixed motor, 0.5A and immediate OFF required')
    data = image()
    baseline()
    if not (args.stage_off or args.execute_powered or args.restore_b_drive_off):
        print('OFFLINE PASS: pinned intent FSM A and preserved B725; no devices')
        return 0
    kind = 'stage' if args.stage_off else 'run' if args.execute_powered else 'restore'
    name = 'intent-fsm-' + kind + '-' + str(time.time_ns())
    row = dict(mode=kind, pass_=False, start_attempts=0, automatic_retry=False,
        image_sha256=SHA, elf_sha256=ELF_SHA, steps=[], commands=[], uart=[], samples=[],
        postflight={}, physical_power_off=args.drive_off_connected_fixed,
        powered_no_alarm=args.drive_on_no_alarm_fixed_05a_emergency_off_ready,
        host_limit_seconds=2.0, motor_connected_fixed=True, receipt_path=str(TMP / (name + '.json')))
    old.prior.checkpoint(row, 'prepared')
    try:
        if args.stage_off:
            stage(row, name, data)
        elif args.execute_powered:
            execute(row, name, args.execute_powered, data)
        else:
            restore(row, name, args.restore_b_drive_off, data)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:
                hw.emergency_off(row, TMP / (name + '-failed.bin'))
            except Exception as cleanup:
                row['cleanup_error'] = str(cleanup)
    old.prior.checkpoint(row, 'complete' if row['pass_'] else 'aborted')
    print(('PASS: ' if row['pass_'] else 'FAIL: ') + row['receipt_path'], flush=True)
    if row.get('failure'):
        print(row['failure'], flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
