"""Exact trace A: OFF stage, separate ON no-START trial, OFF B restore.

The image is HARD_OFF=0, not a compile-time hard-off image. Its existing READY
path computes with SD/MOE/CCER off; the console cannot issue a motion command.
Default is file verification only. Never retries activation or forces health.
"""
import argparse
import json
from pathlib import Path
import time

import pipeline_closed_loop_board_test as candidate
import pipeline_closed_loop_trial as trial
import current_fault_trace_report as trace
from original_closed_loop_updated_stage import debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from tighten_synthetic_swd_recovery import latest_meta

ROOT, OUTPUT, PRIVATE = candidate.ROOT, candidate.OUTPUT, candidate.PRIVATE
IMAGE = ROOT/'foc2_app_a/build/CurrentFaultTrace/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = '4f886e22078594215d8436fa8ab35b09f2040fda4cd443cccfd1bc3463e6591d'
ELF_SHA = '2d461690cbd6fc1183d189d0eb566f8ba166b60b026bb061b83cfeb4c9ef6e6e'
SIZE = 229316
PREFIX = 'current-fault-trace-'
BASE_RECEIPT = OUTPUT/'protected-pipeline-restore-1792228705413884300.json'
BASE_SHA = '1c0e575a570357145f77b299082360bc487c3309628e4261859ad7ad97cba46d'
BASE_META = (1112493908,3,2,0,0,619,228940,2432693926,210916,453748590,0,2575530934)
B_SHA = '9fd54166df782cce3e737ecfebe67bc4aff8f15a005fca1f1136c91bb8786f44'


def image():
    data = IMAGE.read_bytes()
    receipt = json.loads((ROOT/'tests/current_fault_trace_build/receipt.json').read_text('utf-8'))
    if (len(data) != SIZE or candidate.digest(data) != SHA or
            candidate.digest(ELF.read_bytes()) != ELF_SHA or
            candidate.image_info(data)[0] != 'A' or candidate.MARKER not in data):
        raise ValueError('Exact trace A BIN/ELF required')
    if (any(receipt.get(k) is not False for k in
            ('hardware_access','motor_started','boot_selection_changed','control_policy_changed')) or
            receipt.get('test_count') != 54 or
            not any(b.get('slot') == 'a' and b.get('profile') == 'CurrentFaultTrace' and
                    b.get('linked') is True and b.get('bin_sha256') == SHA and
                    b.get('elf_sha256') == ELF_SHA and b.get('trace_symbols_present') is True
                    for b in receipt.get('builds', []))):
        raise ValueError('Matching 54-test successful offline build receipt required')
    return data


def configure():
    # Reuse byte/erase-page transaction and existing no-motion READY gates only.
    # Historical tools retain their on-disk constants and behavior.
    for name in ('IMAGE','ELF','SHA','ELF_SHA','SIZE','PREFIX','BASE_RECEIPT',
                 'BASE_SHA','BASE_META','B_SHA'):
        setattr(candidate, name, globals()[name])
    candidate.image = image
    candidate.configure_transaction()


def stage(row, run, data):
    tx = candidate.tx
    expected, before = tx.baseline()
    row['hardware_attempted'] = True
    inspection = PRIVATE/(run+'-inspection.bin')
    out = debug(row, [*tx.prior.off_gate(0x08040000), *off_report(),
        f'dump_image {{{inspection.as_posix()}}} 0x08000000 0x80000', 'shutdown'])
    row['inspection_outputs'] = check_off(out, (0x08040000,))
    if inspection.read_bytes() != before:
        raise ValueError('Live Flash differs from exact halted B619 baseline; no programming')
    row['inspection_pass'] = True
    print('INSPECT PASS: exact confirmed B619; SD/MOE/CCER off', flush=True)
    staged = PRIVATE/(run+'-staged.bin')
    row['programming_attempted'] = True
    out = debug(row, tx.stage_commands(PRIVATE/(run+'-prewrite.bin'), expected, staged))
    row['staged_outputs'] = check_off(out, (0,0x08000000))
    actual = staged.read_bytes()
    tx.compare_stage(before, actual, data)
    row.update(pass_=True, staged_backup=str(staged), staged_sha256=candidate.digest(actual),
        final_metadata=list(latest_meta(actual)), all_bytes_outside_a_pages_unchanged=True,
        final_outputs_off=True, final_cpu_halted=True, activation=False)
    print('STAGE PASS: trace A verified; B619/private/metadata unchanged; not activated', flush=True)


def load_trial_stage(path, data):
    path = Path(path).resolve()
    capture, raw = candidate.tx.load_stage(path, data)
    row = json.loads(path.read_text('utf-8'))
    if row.get('elf_sha256') != ELF_SHA:
        raise ValueError('Stage ELF identity mismatch')
    return capture, raw


def decode(row, data):
    trial.decode(row, data)
    if not row.get('ram_backup') or row.get('snapshot_vtor') != 0x08008000:
        return
    ram = candidate.tx.prior.private_path(row['ram_backup']).read_bytes()
    flash = candidate.tx.prior.private_path(row['final_backup']).read_bytes()
    if len(ram) != 0x20000 or flash[0x8000:0x8000+SIZE] != data:
        raise ValueError('Trace requires same-session exact A Flash/RAM')
    symbols = trace.schema.symbols(ELF)
    address, size = symbols['foc_current_fault_trace']
    header, frames = trace.decode(ram[address-0x20000000:address-0x20000000+size])
    row['trace'] = dict(header=header, frames=frames,
        timing_scope='includes initial armed trace and post-freeze path; not a per-state WCET proof')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stage-inactive-a', action='store_true')
    modes.add_argument('--trial-from-stage', type=Path)
    modes.add_argument('--restore-from-trial', type=Path)
    parser.add_argument('--drive-12v-off-motor-disconnected', action='store_true')
    parser.add_argument('--drive-12v-on-no-alarm-motor-disconnected', action='store_true')
    args = parser.parse_args()
    mode = ('stage' if args.stage_inactive_a else 'trial' if args.trial_from_stage else
            'restore' if args.restore_from_trial else None)
    if mode in ('stage','restore') and not args.drive_12v_off_motor_disconnected:
        parser.error('Physical 12 V OFF / motor disconnected required')
    if mode == 'trial' and not args.drive_12v_on_no_alarm_motor_disconnected:
        parser.error('Physical 12 V ON / no alarm / motor disconnected required')
    data = image()
    if mode is None:
        print('OFFLINE PASS: exact trace A files; no hardware/private access')
        return 0
    configure()
    run = PREFIX+mode+'-'+str(time.time_ns())
    row = dict(pass_=False, mode=mode, image_sha256=SHA, elf_sha256=ELF_SHA,
        image_bytes=SIZE, steps=[], samples=[], hardware_attempted=False,
        programming_attempted=False, trial_requests=0, motor_commands=0,
        original_start_runner_invocations=0, automatic_retry=False,
        force_confirmation=False, direct_metadata_write=False, protection_edits=False,
        image_compile_time_hard_off=False, motor_closed_loop_verified=False)
    try:
        if mode == 'stage':
            stage(row, run, data)
        elif mode == 'trial':
            row['stage'] = str(args.trial_from_stage.resolve())
            # Do not expose run_trial's optional motion parameter to this CLI.
            trial.load_stage = lambda d: load_trial_stage(args.trial_from_stage, d)
            trial.run_trial(row, run, data, motion=False)
        else:
            previous = candidate.tx.read_receipt(args.restore_from_trial, 'trial')
            if previous.get('original_start_runner_invocations') != 0:
                raise ValueError('Only zero-START trace trial can be restored here')
            candidate.tx.restore(row, run, data, args.restore_from_trial)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        if ((row.get('programming_attempted') or row.get('restore_attempted')) and
                not row.get('final_cpu_halted')):
            try:
                emergency_off(row, PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
        print('FAILED: '+str(error), flush=True)
    finally:
        if mode == 'trial':
            row['host_motor_commands'] = 0  # Console allowlist, no START runner invocation.
            row['host_uart_trial_commits'] = 0  # Trial uses existing bootloader SRAM mailbox.
            try:
                decode(row, data)
            except BaseException as error:
                row.update(pass_=False, decode_failure=str(error))
        path = OUTPUT/(run+'.json')
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(path), flush=True)
        if row.get('measured'):
            print(json.dumps(row['measured'], indent=2), flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
