"""Stage the pinned startup-evidence A ONLY, retaining confirmed B549.

Default is offline. Authorized staging requires drive 12 V off, the exact
previously halted B549 full-Flash baseline, and output-off register proof.
Never resume an APP, activate a trial, write metadata, or issue motor commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from firmware_transfer_iap import ROOT, image_info
from latest_original_fsm_stage import baseline, full_compare_commands, off_commands
from original_closed_loop_updated_stage import check_off, debug, off_report
from tighten_synthetic_swd_recovery import latest_meta
from zero_retest_deploy import compare_flash

OUTPUT = ROOT / 'safety_backups/protected-closed-loop-20261014'
PRIVATE = OUTPUT / 'private'
PRIOR = OUTPUT / 'latest-count-only-trial-1792055325392397800.json'
BASELINE = PRIVATE / 'latest-count-only-trial-1792055325392397800-final.bin'
IMAGE = ROOT / 'foc2_app_a/build/LatestOriginalStartupEvidence/foc2.bin'
SHA = 'b9ef16c8561d279e93db06419237d0cb5e81daafe40f964c51e33dd115aae411'
SIZE = 211004
B_SHA = '689c533abc257fd0ef6933ae9855c07bff5126fa277b3f079f854c74e469d909'
META = (1112493908, 3, 2, 0, 0, 549, 207972, 98608031,
        208564, 4225420029, 0, 2344036199)


def pinned_image():
    data = IMAGE.read_bytes()
    if (len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA
            or image_info(data)[0] != 'A'):
        raise RuntimeError('Exact startup-evidence A candidate required')
    for marker in (b'STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1',
                   b'NAME=LATEST_ORIGINAL_FSM', b'MAX=OFF SEG_MAX=OFF',
                   b'RPM=20 LEASE_US=400000 QUALIFIED=0'):
        if marker not in data:
            raise RuntimeError('Candidate identity missing')
    return data


def validate_baseline(raw):
    baseline(raw, (2, 0, 0, 549))
    if (latest_meta(raw) != META
            or hashlib.sha256(raw[0x40000:0x40000 + META[8]]).hexdigest() != B_SHA):
        raise RuntimeError('Confirmed B549 image/metadata mismatch')


def load_baseline():
    row = json.loads(PRIOR.read_text('utf-8'))
    if (Path(row['final_backup']).resolve() != BASELINE.resolve()
            or row.get('image_sha256') != B_SHA
            or any(row.get(key) is not True for key in
                   ('final_outputs_off', 'final_cpu_halted', 'all_flash_unchanged',
                    'all_app_and_private_bytes_unchanged'))
            or row.get('original_start_runner_invocations') != 1
            or tuple(row.get('final_metadata', ())) != META):
        raise RuntimeError('Exact halted/output-off B549 receipt required')
    raw = BASELINE.read_bytes()
    validate_baseline(raw)
    return raw


def gates():
    return ['init',
        'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not already halted"}',
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Not halted confirmed B"}',
        'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Outputs not off"}']


def stage_commands(prewrite, inspected, staged):
    return [*gates(), *full_compare_commands(prewrite, inspected), 'reset halt',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted in bootloader"}',
        *off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
        *off_report(), 'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
        'halt', 'shutdown']


def verify_staged(before, actual, image):
    result = compare_flash(before, actual, image, 'A', staged=True)
    if before[:0x8000] != actual[:0x8000] or before[0x40000:] != actual[0x40000:]:
        raise RuntimeError('Flash outside inactive A changed')
    if latest_meta(actual) != META:
        raise RuntimeError('Staging changed confirmed B549 metadata')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-inactive-a-stage', action='store_true')
    parser.add_argument('--drive-12v-off', action='store_true')
    args = parser.parse_args()
    image = pinned_image()
    if not args.allow_inactive_a_stage:
        print('OFFLINE PASS: pinned startup-evidence A; no hardware access')
        return
    if not args.drive_12v_off:
        parser.error('Physical drive 12 V OFF required')
    before = load_baseline()
    run = 'startup-evidence-a-stage-' + str(time.time_ns())
    receipt = OUTPUT / (run + '.json')
    inspected = PRIVATE / (run + '-before.bin')
    prewrite = PRIVATE / (run + '-prewrite.bin')
    staged = PRIVATE / (run + '-staged.bin')
    row = dict(pass_=False, image_sha256=SHA, image_bytes=SIZE, target='A',
        confirmed_retained='B549', steps=[], baseline_receipt=str(PRIOR),
        activation=False, motor_commands=0, trial_mailbox_write=False,
        direct_metadata_write=False, force_confirmation=False, automatic_retry=False,
        drive_12v_off_user_confirmed=True)
    mutation_attempted = False
    try:
        # Read-only inspection. Do not reset or change GPIO on a failed baseline gate.
        output = debug(row, [*gates(), *off_report(),
            f'dump_image {{{inspected.as_posix()}}} 0x08000000 0x80000', 'shutdown'])
        row['before_outputs'] = check_off(output, (0x08040000,))
        live = inspected.read_bytes()
        if live != before:
            raise RuntimeError('Live full Flash differs from exact last B549 capture')
        validate_baseline(live)
        row.update(before_backup=str(inspected), before_sha256=hashlib.sha256(live).hexdigest())
        print('INSPECT PASS: exact halted B549; SD/PWM/timer off; full backup retained', flush=True)
        mutation_attempted = True
        output = debug(row, stage_commands(prewrite, inspected, staged))
        row['outputs'] = check_off(output, (0, 0x08000000))
        actual = staged.read_bytes()
        row['comparison'] = verify_staged(live, actual, image)
        row.update(pass_=True, staged_backup=str(staged),
            staged_sha256=hashlib.sha256(actual).hexdigest(),
            metadata_unchanged=True, all_bytes_outside_a_unchanged=True,
            cpu_reset_halted=True, final_outputs_off=True,
            generation=latest_meta(actual)[5], final_metadata=list(latest_meta(actual)))
        print('STAGE PASS: A byte-exact; confirmed B549/bootloader/data unchanged; NOT activated', flush=True)
    except BaseException as error:
        row['failure'] = str(error)
        if mutation_attempted:
            try:
                output = debug(row, ['init', 'halt', *off_commands(), *off_report(),
                    'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}', 'shutdown'])
                row['cleanup_outputs'] = check_off(output, (0, 0x08000000, 0x08040000))
                row['error_cleanup_halted_off'] = True
            except BaseException as cleanup:
                row['cleanup_error'] = str(cleanup)
        raise
    finally:
        receipt.write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
