"""Pinned latest backend/original FSM staging; drive power OFF, no motor START.

Recover only the already-confirmed A through the existing bootloader mailbox,
halt at A's reset entry before application instructions, then stage inactive B.
Never force-confirm B, program metadata directly, or edit private parameters.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

from firmware_transfer_iap import ROOT, image_info
from original_closed_loop_updated_stage import debug, check_off, off_report, A_SHA
from tighten_synthetic_swd_recovery import latest_meta
from zero_retest_deploy import compare_flash

OUTPUT = ROOT / 'safety_backups/protected-closed-loop-20261014'
PRIVATE = OUTPUT / 'private'
INSPECTION = OUTPUT / 'latest-original-before-1792053558652116400.json'
IMAGE = ROOT / 'foc2_app_b/build/LatestFeedbackOriginalFsm/foc2.bin'
SHA = '7adb6bb59b56d1d6b0358072a1cd64ed06611aa01a6b543ba26a343ffecf528e'
SIZE = 208564


def pinned_image():
    data = IMAGE.read_bytes()
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA or image_info(data)[0] != 'B':
        raise RuntimeError('Exact latest-backend/original-FSM B image required')
    if b'LATEST_ORIGINAL_FSM' not in data or b'USE_ORIGINAL_START' not in data:
        raise RuntimeError('New profile identity missing')
    return data


def mailbox(command, requester, target, size=0, crc=0):
    if (command, requester, target) not in ((3, 1, 1), (2, 1, 2)):
        raise ValueError('Only existing-confirmed A recovery or A-to-B trial')
    if command == 2 and (size != SIZE or crc != zlib.crc32(pinned_image())):
        raise ValueError('Trial must bind exact latest B')
    body = struct.pack('<7I', 0x584F424D, 1, command, requester, target, size, crc)
    return struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))


def write_mailbox(words):
    return ['mww 0x2001FFC0 0', *[
        f'mww {0x2001FFC0 + i * 4:#x} {words[i]:#x}' for i in range(1, 8)],
        f'mww 0x2001FFC0 {words[0]:#x}']


def baseline(raw, expected):
    if len(raw) != 0x80000 or latest_meta(raw)[2:6] != expected:
        raise RuntimeError('Unexpected current boot state')
    if hashlib.sha256(raw[0x8000:0x8000 + 207972]).hexdigest() != A_SHA:
        raise RuntimeError('Preserved A fallback mismatch')
    return latest_meta(raw)


def full_compare_commands(live, expected):
    return [f'dump_image {{{live.as_posix()}}} 0x08000000 0x80000',
        'proc task_readbin {path} {set f [open $path rb]; set b [read $f]; close $f; return $b}',
        f'if {{[task_readbin {{{live.as_posix()}}}] ne [task_readbin {{{expected.as_posix()}}}]}} {{error "Live Flash changed"}}']


def off_commands():
    return ['mmw 0x4002104C 0x4 0', 'mww 0x48000818 0x00400000',
        'mmw 0x48000800 0x1000 0x2000', 'mmw 0x40021060 0x800 0',
        'mww 0x40012C20 0', 'mmw 0x40012C44 0 0xC000', 'mmw 0x40012C00 0 1']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recover-confirmed-a-and-stage-b', action='store_true')
    p.add_argument('--drive-12v-off', action='store_true')
    args = p.parse_args()
    image = pinned_image()
    if not args.recover_confirmed_a_and_stage_b:
        print('OFFLINE PASS: exact latest B; no hardware operation')
        return
    if not args.drive_12v_off:
        p.error('Physical drive 12 V OFF required')
    prior = json.loads(INSPECTION.read_text('utf-8'))
    path = Path(prior['before_backup']).resolve()
    if path.parent != PRIVATE.resolve() or prior.get('pass_') is not True:
        raise RuntimeError('Exact successful current inspection required')
    before = path.read_bytes()
    baseline(before, (1, 2, 1, 542))
    if hashlib.sha256(before).hexdigest() != prior['before_sha256']:
        raise RuntimeError('Inspection backup changed')
    run = 'latest-original-stage-' + str(time.time_ns())
    receipt = OUTPUT / (run + '.json')
    live = PRIVATE / (run + '-before.bin')
    recovered = PRIVATE / (run + '-recovered.bin')
    staged = PRIVATE / (run + '-staged.bin')
    entry = struct.unpack_from('<I', before, 0x8004)[0] & ~1
    if not 0x08008000 <= entry < 0x08040000:
        raise RuntimeError('A reset entry invalid')
    row = dict(pass_=False, image_sha256=SHA, image_bytes=SIZE, steps=[],
               motor_commands=0, new_b_activation=False, direct_metadata_write=False,
               force_confirm_b=False, drive_12v_off_user_confirmed=True)
    try:
        # Gate every mutation on a byte-identical current Flash capture.
        output = debug(row, ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
            'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected old halted B"}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Output not off"}',
            *full_compare_commands(live, path), 'reset halt',
            f'bp {entry:#x} 2 hw', *write_mailbox(mailbox(3, 1, 1)),
            'reset run', 'wait_halt 25000', f'rbp {entry:#x}',
            f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not stopped at A reset entry"}}',
            *off_commands(), *off_report(),
            f'dump_image {{{recovered.as_posix()}}} 0x08000000 0x80000', 'shutdown'])
        row['recovery_outputs'] = check_off(output, (0, 0x08000000, 0x08008000))
        raw = recovered.read_bytes()
        baseline(raw, (1, 0, 0, 543))
        if raw[:0x7E800] != before[:0x7E800] or raw[0x7F800:] != before[0x7F800:]:
            raise RuntimeError('Recovery changed non-metadata Flash')
        row['recovered_backup'] = str(recovered)
        row['recovered_metadata'] = list(latest_meta(raw))
        print('RECOVERY PASS: existing confirmed A selected by bootloader; halted before A app', flush=True)
        output = debug(row, ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU no longer halted"}',
            *full_compare_commands(PRIVATE / (run + '-prewrite.bin'), recovered),
            'reset halt', *off_commands(),
            f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
            f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
            *off_report(), 'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
            'halt', 'shutdown'])
        row['outputs'] = check_off(output, (0, 0x08000000))
        actual = staged.read_bytes()
        row['comparison'] = compare_flash(raw, actual, image, 'B', staged=True)
        if raw[:0x40000] != actual[:0x40000] or raw[0x78000:] != actual[0x78000:]:
            raise RuntimeError('Flash outside inactive B changed')
        row.update(pass_=True, staged_backup=str(staged),
                   staged_sha256=hashlib.sha256(actual).hexdigest(),
                   metadata_unchanged_by_stage=True, all_bytes_outside_b_unchanged=True,
                   cpu_reset_halted=True)
        print('STAGE PASS: latest backend + original FSM; B byte-exact; A/data preserved; NOT activated', flush=True)
    except BaseException as error:
        row['failure'] = str(error)
        # Never resume after uncertain breakpoint/programming results.
        try:
            debug(row, ['init', 'halt', *off_commands(), *off_report(), 'shutdown'])
            row['error_cleanup_halted_off'] = True
        except BaseException as cleanup:
            row['cleanup_error'] = str(cleanup)
        raise
    finally:
        receipt.write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
