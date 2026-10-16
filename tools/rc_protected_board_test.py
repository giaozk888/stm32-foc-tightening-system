"""Pinned protected RC B candidate staging only; offline by default.

Explicit drive-power-OFF/disconnected phase. Requires exact halted/off A564,
preserves A, bootloader, metadata and private regions; no resume or START.
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

PRIOR = OUTPUT / 'rc-sampling-trial-1792121761791953100.json'
BASELINE_SHA = 'bec7e9bfa24ce103672b49ba311a7df850bc995be9862b3f236134b222473fb1'
META = (1112493908, 3, 1, 0, 0, 564, 208236, 1538858691,
        210116, 1868256407, 0, 1474416059)
A_SHA = '951a9381cd18e5614b685d8ca978e466d0746252a03c3554892595c549a0ccf3'
OLD_B_SHA = '2450f5a6da36c0698690aa2353fd1f76758e4b7401453fb7f361cfab1e72c61b'
IMAGE = ROOT / 'foc2_app_b/build/RcSamplingProtectedCandidate/foc2.bin'
SHA = '61abcdc9ee6c92a34c4920562e8a3e6e9ac6404653e56b7466020f4257b752df'
SIZE = 210724


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned_image():
    image = IMAGE.read_bytes()
    if len(image) != SIZE or digest(image) != SHA or image_info(image)[0] != 'B':
        raise ValueError('Exact RC protected B candidate required')
    for marker in (b'NAME=RC_PROTECTED_CANDIDATE HARD_OFF=0 ADAPT=1 FSM=ORIGINAL',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000', b'USE_ORIGINAL_START',
                   b'RAM ENABLED=1 HARD_OFF=0 DEADLINE_US=50',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
                   b'BOTTOM_LATE=%lu GUARD=%u HW_VERIFIED=0',
                   b'STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1'):
        if marker not in image:
            raise ValueError('Protected candidate identity/guard missing')
    return image


def validate_baseline(raw):
    if len(raw) != 0x80000 or digest(raw) != BASELINE_SHA or latest_meta(raw) != META:
        raise ValueError('Exact normally confirmed A564 full capture required')
    if (digest(raw[0x8000:0x8000 + META[6]]) != A_SHA or
            digest(raw[0x40000:0x40000 + META[8]]) != OLD_B_SHA):
        raise ValueError('A564 or prior B561 image mismatch')


def load_before():
    row = json.loads(PRIOR.read_text(encoding='utf-8'))
    path = Path(row['final_backup']).resolve()
    if (path.parent != PRIVATE.resolve() or row.get('pass_') is not True or
            row.get('image_sha256') != A_SHA or row.get('final_sha256') != BASELINE_SHA or
            tuple(row.get('final_metadata', ())) != META or row.get('host_motor_commands') != 0 or
            any(row.get(k) is not True for k in ('normally_confirmed', 'final_cpu_halted',
                'final_outputs_off', 'all_app_and_private_bytes_unchanged'))):
        raise ValueError('Exact stopped A564 receipt required')
    raw = path.read_bytes()
    validate_baseline(raw)
    return path, raw


def compare_stage(before, actual, image):
    validate_baseline(before)
    if len(actual) != 0x80000 or actual[0x40000:0x40000 + len(image)] != image:
        raise ValueError('Full capture and exact new B required')
    end = 0x40000 + len(image)
    erased_end = (end + 0x7ff) & ~0x7ff
    if actual[end:erased_end] != b'\xff' * (erased_end - end):
        raise ValueError('Unexpected data in last erased B page')
    if actual[:0x40000] != before[:0x40000] or actual[erased_end:] != before[erased_end:]:
        raise ValueError('Bytes outside new B erase pages changed')
    if latest_meta(actual) != META:
        raise ValueError('Staging changed metadata')


def inspect_commands(live, baseline):
    return [*output_gate(0x08008000),
            'if {[mrw 0x40012C00] & 1} {error "Expected stopped timer"}',
            *full_compare_commands(live, baseline), *off_report(),
            'echo CEN=[mrw 0x40012C00]', 'shutdown']


def stage_commands(live, baseline, staged):
    return [*inspect_commands(live, baseline)[:-1], 'reset halt',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}',
            *off_commands(),
            f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
            f'verify_image {{{IMAGE.as_posix()}}} 0x08040000 bin',
            f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
            *off_report(),
            'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
            'halt', 'shutdown']


def stage(row, run, image):
    baseline, before = load_before()
    row['baseline_backup'] = str(baseline)
    row['hardware_attempted'] = True
    inspected = PRIVATE / (run + '-inspection.bin')
    report = debug(row, inspect_commands(inspected, baseline))
    row['before_outputs'] = check_off(report, (0x08008000,))
    validate_baseline(inspected.read_bytes())
    row['inspection_pass'] = True
    staged = PRIVATE / (run + '-staged.bin')
    row['mutation_attempted'] = True
    report = debug(row, stage_commands(PRIVATE / (run + '-before.bin'), baseline, staged))
    row['outputs'] = check_off(report, (0, 0x08000000))
    actual = staged.read_bytes()
    compare_stage(before, actual, image)
    row.update(pass_=True, staged_backup=str(staged), staged_sha256=digest(actual),
               metadata_unchanged=True, all_bytes_outside_b_pages_unchanged=True,
               preserved_a_sha256=A_SHA, prior_b_backup_sha256=OLD_B_SHA,
               final_cpu_halted=True, final_outputs_off=True, activation=False)
    print('STAGE PASS: protected RC B byte-exact; A564/data retained; NOT activated', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-inactive-b', action='store_true')
    parser.add_argument('--drive-12v-off', action='store_true')
    parser.add_argument('--motor-disconnected', action='store_true')
    args = parser.parse_args()
    image = pinned_image()
    if not args.stage_inactive_b:
        print('OFFLINE PASS: pinned protected RC B; no private or hardware access')
        return 0
    if not args.drive_12v_off or not args.motor_disconnected:
        parser.error('Confirmed drive 12 V OFF and disconnected motor required')
    run = 'rc-protected-stage-' + str(time.time_ns())
    row = dict(pass_=False, mode='stage', image_sha256=SHA, image_bytes=SIZE, steps=[],
               baseline_receipt=str(PRIOR), hardware_attempted=False, mutation_attempted=False,
               motor_commands=0, trial_requests=0, activation=False, automatic_retry=False,
               force_confirmation=False, direct_metadata_write=False,
               drive_12v_off_user_confirmed=True, motor_disconnected_user_confirmed=True)
    try:
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
