"""Pinned inactive-B staging and normal health-confirmed boot, never START.

Full captures remain in ignored tmp/. The stage command never resets or selects
B. The trial command uses the existing bootloader mailbox and health protocol.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import zlib

from firmware_transfer_iap import fields, image_info
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from pipeline_closed_loop_trial import Console
from tighten_synthetic_swd_recovery import latest_meta

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / 'foc2_app_b/build/LoadedFsmTrial/foc2.bin'
BASE = ROOT / 'tmp/current-polarity-restored-a-20261018.bin'
SHA = '1fd1afa9156bb72e71d42a16378d1e0a2cc76d167d9037dd5b3a869d63256826'
BASE_SHA = 'b3624950694ffbb7c63a9babcc3edc7dae2167e743f209714d1f253b4aa416a6'
TMP = ROOT / 'tmp'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image():
    data = IMAGE.read_bytes()
    if len(data) != 227964 or digest(data) != SHA or image_info(data)[0] != 'B':
        raise ValueError('Exact tested loaded-FSM B image required')
    for marker in (b'RPM=20 LEASE_US=12000000 QUALIFIED=0',
                   b'METHOD=TWO_SAMPLE', b'FILTER=NONE OC=RAW_CONFIRM_4'):
        if marker not in data:
            raise ValueError('Loaded profile/protection marker absent')
    return data


def stage(row, name, data, recovery=None):
    baseline = BASE.read_bytes()
    if len(baseline) != 0x80000 or digest(baseline) != BASE_SHA:
        raise ValueError('Exact confirmed-A631 baseline required')
    if latest_meta(baseline)[2:6] != (1, 0, 0, 631):
        raise ValueError('Confirmed A631 with no pending trial required')
    expected = BASE
    if recovery is not None:
        failed = json.loads(recovery.read_text('utf-8'))
        expected = Path(failed['final_backup'])
        partial = expected.read_bytes()
        if (expected.resolve().parent != TMP.resolve() or failed.get('pass_') is not False
                or failed.get('image_sha256') != SHA or failed.get('cleanup_error')
                or not failed.get('final_outputs_off') or not failed.get('final_cpu_halted')
                or partial[:0x40000] != baseline[:0x40000]
                or partial[0x78000:] != baseline[0x78000:]):
            raise ValueError('Failed stage did not preserve confirmed A/private bytes')
        row['recovery_receipt'] = str(recovery)
    before = TMP / (name + '-before.bin')
    after = TMP / (name + '-staged.bin')
    row['hardware_attempted'] = True
    debug(row, ['init', 'halt',
        'if {[mrw 0xE000ED08] != 0x08008000} {error wrong_current_slot}',
        *off_commands(), *full_compare_commands(before, expected), 'shutdown'])
    row['programming_attempted'] = True
    debug(row, ['init', 'halt',
        *full_compare_commands(TMP / (name+'-recheck.bin'), before),
        # App DMA/IRQs must be reset before OpenOCD runs a Flash algorithm in RAM.
        'reset halt', *off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08040000 bin',
        f'dump_image {{{after.as_posix()}}} 0x08000000 0x80000', 'shutdown'])
    actual = after.read_bytes()
    end = (0x40000 + len(data) + 0x7ff) & ~0x7ff
    if (len(actual) != 0x80000 or actual[:0x40000] != baseline[:0x40000]
            or actual[end:] != baseline[end:]
            or actual[0x40000:0x40000+len(data)] != data
            or actual[0x40000+len(data):end] != b'\xff' * (end-0x40000-len(data))):
        raise RuntimeError('Full Flash verification failed')
    row.update(staged_capture=str(after), staged_sha256=digest(actual),
               metadata=list(latest_meta(actual)), slot_a_and_private_unchanged=True,
               activation=False, pass_=True)


def trial(row, name, receipt, data, resume_confirmed=False):
    staged_row = json.loads(receipt.read_text('utf-8'))
    if resume_confirmed:
        staged = Path(staged_row['final_backup'])
        captured = staged.read_bytes()
        baseline = BASE.read_bytes()
        fw = staged_row.get('last_fw', {})
        if (staged.resolve().parent != TMP.resolve() or staged_row.get('image_sha256') != SHA
                or not staged_row.get('normally_confirmed')
                or not staged_row.get('final_outputs_off') or not staged_row.get('final_cpu_halted')
                or staged_row.get('cleanup_error')
                or any(fw.get(k) != v for k,v in (('CURRENT','B'),('CONFIRMED','B'),('PENDING','-')))
                or latest_meta(captured)[2:5] != (2,0,0)
                or captured[:0x40000] != baseline[:0x40000]
                or captured[0x40000:0x40000+len(data)] != data
                or captured[0x78000:0x7e800] != baseline[0x78000:0x7e800]
                or captured[0x7f800:] != baseline[0x7f800:]):
            raise ValueError('Exact stopped confirmed B and preserved A/private bytes required')
        row['read_wait_recovery_receipt'] = str(receipt)
    else:
        staged = Path(staged_row['staged_capture'])
        if (staged.resolve().parent != TMP.resolve() or staged_row.get('pass_') is not True
                or staged_row.get('image_sha256') != SHA
                or digest(staged.read_bytes()) != staged_row['staged_sha256']):
            raise ValueError('Matching verified inactive-B stage required')
    port = open_port()
    uart = Console(port)
    try:
        body = struct.pack('<7I', 0x584f424d, 1, 2, 1, 2, len(data), zlib.crc32(data))
        mailbox = struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))
        row['hardware_attempted'] = True
        commands = ['init', 'halt',
            *full_compare_commands(TMP/(name+'-pretrial.bin'), staged),
            'reset halt', *off_commands()]
        if not resume_confirmed:
            commands += write_mailbox(mailbox)
        commands += ['reset run', 'shutdown']
        debug(row, commands)
        row['trial_submitted'] = not resume_confirmed
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            try:
                fw = fields(uart.query('FW STATUS', .6))
            except TimeoutError:
                continue
            row['last_fw'] = fw
            if fw.get('CURRENT') == 'A' and fw.get('PENDING') == '-':
                raise RuntimeError('Trial rejected/rolled back to A; no retry')
            if fw.get('CURRENT') != 'B':
                continue
            try:
                state = fields(uart.query('MOTOR TEST STATUS', .6))
            except TimeoutError:
                # Normal health confirmation resets once. Only reads may be
                # repeated inside this unchanged absolute startup deadline.
                continue
            row['last_state'] = state
            if any(state.get(k) != '0' for k in ('SD', 'MOE', 'CCER', 'FLAGS', 'FAULT')):
                raise RuntimeError('Startup fault or unexpected gate state')
            if state.get('STATE') == '4':
                raise RuntimeError('Startup protection fault')
            if (fw.get('CONFIRMED') == 'B' and fw.get('PENDING') == '-'
                    and fw.get('ATTEMPTS') == '0' and state.get('STATE') == '1'
                    and state.get('ZERO') == '3'):
                try:
                    after_fw = fields(uart.query('FW STATUS', .6))
                except TimeoutError:
                    continue
                if after_fw == fw:
                    row['normally_confirmed'] = True
                    break
            uart.poll(.02)
        else:
            raise TimeoutError('Normal B confirmation absent within 60 seconds')
        row['preflight'] = {}
        for command in ('MOTOR TEST PROFILE', 'SELFTEST STATUS', 'MOTOR TEST ZERO',
                        'MOTOR TEST FAULT', 'MOTOR TEST TIMING', 'STATUS', 'ANALOG SAFE STATUS'):
            row['preflight'][command] = uart.query(command)
        # MonitorTask wakes at 3 s and emits this section at >=5 s. Allow
        # two report opportunities; its phase restarts at health confirmation.
        end = time.monotonic()+12
        while time.monotonic() < end:
            uart.poll(.05)
        final = fields(uart.query('MOTOR TEST STATUS'))
        if any(final.get(k) != v for k, v in
               (('STATE', '1'), ('ZERO', '3'), ('FAULT', '0'), ('FLAGS', '0'),
                ('SD', '0'), ('MOE', '0'), ('CCER', '0'))):
            raise RuntimeError('Ready state lost during idle observation')
        telemetry = '\n'.join(uart.lines)
        measured = {}
        for key in ('wall_max_us', 'deadline_miss', 'actual_late_commit_count',
                    'actual_margin_min_us'):
            matches = re.findall(r'\b'+key+r'=([+-]?[0-9.]+)', telemetry)
            if not matches:
                raise RuntimeError('Missing timing measurement: '+key)
            measured[key] = float(matches[-1])
        row['timing'] = measured
        if (measured['wall_max_us'] >= 50 or measured['deadline_miss'] != 0
                or measured['actual_late_commit_count'] != 0
                or measured['actual_margin_min_us'] <= 1):
            raise RuntimeError('Loaded profile timing preflight failed')
        row.update(pass_=True, startup_ready=True)
    finally:
        row['uart'] = uart.lines
        port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stage-off', action='store_true')
    modes.add_argument('--recover-stage-off', type=Path)
    modes.add_argument('--trial-powered', type=Path)
    modes.add_argument('--resume-confirmed-powered', type=Path)
    args = parser.parse_args()
    data = image()
    if not (args.stage_off or args.recover_stage_off or args.trial_powered or args.resume_confirmed_powered):
        print('OFFLINE image identity PASS; no device operations')
        return 0
    name = 'loaded-fsm-' + ('trial-' if args.trial_powered or args.resume_confirmed_powered else 'stage-') + str(time.time_ns())
    row = dict(pass_=False, image_sha256=SHA, steps=[], host_start_commands=0,
               automatic_retry=False, direct_metadata_write=False)
    try:
        if args.stage_off or args.recover_stage_off:
            stage(row, name, data, args.recover_stage_off)
        else:
            trial(row, name, args.trial_powered or args.resume_confirmed_powered,
                  data, bool(args.resume_confirmed_powered))
    except Exception as error:
        row.update(pass_=False, failure=str(error))
        if row.get('hardware_attempted'):
            try:
                emergency_off(row, TMP/(name+'-failed.bin'))
            except Exception as cleanup:
                row['cleanup_error'] = str(cleanup)
    path = TMP/(name+'.json')
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(('PASS' if row['pass_'] else 'FAIL') + ': ' + str(path), flush=True)
    if row.get('failure'):
        print(row['failure'], flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
