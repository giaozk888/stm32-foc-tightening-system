"""Pinned RC sampling hard-off diagnostic: offline by default; stage only.

Drive 12 V OFF and motor disconnected are required for staging. Preserve
confirmed B561, bootloader, metadata and private data byte-for-byte. No resume,
trial request, force-confirmation, motor command or automatic retry here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from firmware_transfer_iap import ROOT, image_info
from latest_original_fsm_stage import full_compare_commands, off_commands
from original_closed_loop_updated_stage import OUTPUT, PRIVATE, debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from tighten_synthetic_swd_recovery import latest_meta
from zero_all_rejected_board_test import output_gate

PRIOR = OUTPUT / 'startup-closed-loop-trial-1792065859172936800.json'
BASELINE_SHA = '33a60cdc09aeee6e095f7e5858fd888835199df26f2c38cc076bbab0b5da0a51'
META = (1112493908, 3, 2, 0, 0, 561, 209820, 2832842604,
        210116, 1868256407, 0, 1765156287)
A558_SHA = 'fd6e3c1530ac23ab9bd72f7d812adacccfe437cbaa9feed4764abd8c1c19f2b0'
B561_SHA = '2450f5a6da36c0698690aa2353fd1f76758e4b7401453fb7f361cfab1e72c61b'
IMAGE = ROOT / 'foc2_app_a/build/RcSamplingComputeOnly/foc2.bin'
SHA = '951a9381cd18e5614b685d8ca978e466d0746252a03c3554892595c549a0ccf3'
SIZE = 208236


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned_image():
    data = IMAGE.read_bytes()
    if len(data) != SIZE or digest(data) != SHA or image_info(data)[0] != 'A':
        raise ValueError('Exact RC sampling hard-off A required')
    for marker in (b'ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1',
                   b'RAM ENABLED=1 HARD_OFF=1 DEADLINE_US=50',
                   b'COMPACT ENABLED=1 HARD_OFF=1 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50',
                   b'RC_MIN=%u LATE=%u HW_VERIFIED=0', b'MAX=OFF SEG_MAX=OFF'):
        if marker not in data:
            raise ValueError('RC hard-off identity missing')
    if b'LATEST_ORIGINAL_FSM' in data or b'USE_ORIGINAL_START' in data:
        raise ValueError('Motor-enabled identity forbidden')
    return data


def validate_baseline(raw):
    if len(raw) != 0x80000 or digest(raw) != BASELINE_SHA or latest_meta(raw) != META:
        raise ValueError('Exact stopped B561 full capture required')
    if (digest(raw[0x8000:0x8000 + META[6]]) != A558_SHA
            or digest(raw[0x40000:0x40000 + META[8]]) != B561_SHA):
        raise ValueError('Original A558/B561 images changed')


def load_before():
    row = json.loads(PRIOR.read_text(encoding='utf-8'))
    path = Path(row['final_backup']).resolve()
    if (path.parent != PRIVATE.resolve() or row.get('final_sha256') != BASELINE_SHA
            or row.get('image_sha256') != B561_SHA
            or tuple(row.get('final_metadata', ())) != META
            or any(row.get(k) is not True for k in ('final_outputs_off', 'final_cpu_halted',
                                                   'all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact stopped B561 receipt required')
    raw = path.read_bytes()
    validate_baseline(raw)
    return path, raw


def compare_stage(before, actual, image):
    validate_baseline(before)
    if len(actual) != 0x80000 or actual[0x8000:0x8000 + len(image)] != image:
        raise ValueError('Complete capture and exact new A required')
    # Account for the last erased 2 KiB page, not the entire inactive slot.
    end = 0x8000 + len(image)
    erased_end = (end + 0x7ff) & ~0x7ff
    if actual[end:erased_end] != b'\xff' * (erased_end - end):
        raise ValueError('Unexpected programmed tail in last A page')
    if actual[:0x8000] != before[:0x8000] or actual[erased_end:] != before[erased_end:]:
        raise ValueError('Bytes outside new A erase pages changed')
    if latest_meta(actual) != META:
        raise ValueError('Staging changed metadata')


def inspect_commands(live, baseline):
    return [*output_gate(0x08040000), *full_compare_commands(live, baseline),
            *off_report(), 'echo CEN=[mrw 0x40012C00]', 'shutdown']


def halt_inspect_commands(live, baseline):
    # An explicit OFF-power recovery of debug state only, not a firmware retry.
    # Check slot and disabled outputs before halting; never reset or resume.
    return ['init', *output_gate(0x08040000)[2:], 'halt',
            *output_gate(0x08040000)[1:], *full_compare_commands(live, baseline),
            *off_report(), 'shutdown']


def halt_inspect(row, run):
    path, _ = load_before()
    row['hardware_attempted'] = True
    live = PRIVATE / (run + '-inspection.bin')
    result = debug(row, halt_inspect_commands(live, path))
    row['outputs'] = check_off(result, (0x08040000,))
    validate_baseline(live.read_bytes())
    row.update(pass_=True, inspected_backup=str(live), inspected_sha256=BASELINE_SHA,
               final_cpu_halted=True, final_outputs_off=True, flash_programmed=False)
    print('INSPECTION PASS: B561 exact; halted/off; no reset or Flash write', flush=True)


def stage_commands(live, baseline, staged):
    return [*output_gate(0x08040000), *full_compare_commands(live, baseline),
            'reset halt',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
            *off_commands(),
            f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
            f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
            f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
            *off_report(),
            'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
            'halt', 'shutdown']


def stage(row, run, image):
    path, before = load_before()
    row['baseline_backup'] = str(path)
    row['hardware_attempted'] = True
    # If current state differs, this read-only inspection fails before mutation.
    report = debug(row, inspect_commands(PRIVATE / (run + '-inspection.bin'), path))
    row['before_outputs'] = check_off(report, (0x08040000,))
    row['inspection_pass'] = True
    staged = PRIVATE / (run + '-staged.bin')
    row['mutation_attempted'] = True
    report = debug(row, stage_commands(PRIVATE / (run + '-before.bin'), path, staged))
    row['outputs'] = check_off(report, (0, 0x08000000))
    actual = staged.read_bytes()
    compare_stage(before, actual, image)
    row.update(pass_=True, staged_backup=str(staged), staged_sha256=digest(actual),
               metadata_unchanged=True, all_bytes_outside_a_pages_unchanged=True,
               preserved_b_sha256=B561_SHA, prior_a_backup_sha256=A558_SHA,
               final_cpu_halted=True, final_outputs_off=True, activation=False)
    print('STAGE PASS: RC hard-off A exact; B561/bootloader/metadata/private retained; NOT activated', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stage-inactive-a', action='store_true')
    modes.add_argument('--halt-inspect-b', action='store_true')
    parser.add_argument('--drive-12v-off', action='store_true')
    parser.add_argument('--motor-disconnected', action='store_true')
    args = parser.parse_args()
    image = pinned_image()
    if not args.stage_inactive_a and not args.halt_inspect_b:
        print('OFFLINE PASS: exact RC sampling hard-off A; no private or hardware access')
        return 0
    if not args.drive_12v_off or not args.motor_disconnected:
        parser.error('Confirmed 12 V OFF and motor disconnected required')
    mode = 'inspection' if args.halt_inspect_b else 'stage'
    run = 'rc-sampling-' + mode + '-' + str(time.time_ns())
    row = dict(pass_=False, mode=mode, image_sha256=SHA, image_bytes=SIZE, steps=[],
               baseline_receipt=str(PRIOR), hardware_attempted=False, mutation_attempted=False,
               motor_commands=0, trial_requests=0, activation=False, automatic_retry=False,
               force_confirmation=False, direct_metadata_write=False,
               drive_12v_off_user_confirmed=True, motor_disconnected_user_confirmed=True)
    try:
        if args.halt_inspect_b:
            halt_inspect(row, run)
        else:
            stage(row, run, image)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        print('FAILED: ' + str(error), flush=True)
        if row['mutation_attempted'] and not row.get('final_cpu_halted'):
            try:
                emergency_off(row, PRIVATE / (run + '-failure.bin'))
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        receipt = OUTPUT / (run + '.json')
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt), flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
