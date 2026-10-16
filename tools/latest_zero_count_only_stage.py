"""Stage pinned count-only B; user drive power OFF, no activation or START.

Recover already-confirmed A through the bootloader, stopping at its entry.
Only inactive B is programmed. Raw Flash stays in the restricted evidence dir.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib

import latest_original_fsm_stage as shared
from firmware_transfer_iap import image_info

OUTPUT, PRIVATE = shared.OUTPUT, shared.PRIVATE
IMAGE = shared.ROOT / 'foc2_app_b/build/LatestFeedbackOriginalFsmCountOnly/foc2.bin'
SHA = '689c533abc257fd0ef6933ae9855c07bff5126fa277b3f079f854c74e469d909'
SIZE = 208564
BASELINE = OUTPUT / 'latest-original-trial-1792053995011508600.json'


def pinned_image():
    data = IMAGE.read_bytes()
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA or image_info(data)[0] != 'B':
        raise RuntimeError('Exact count-only latest B required')
    for marker in (b'LATEST_ORIGINAL_FSM', b'USE_ORIGINAL_START', b'MAX=OFF SEG_MAX=OFF'):
        if marker not in data:
            raise RuntimeError('Count-only identity missing')
    if b'MAX=20 SEG_MAX=OFF' in data:
        raise RuntimeError('Old total quota still present')
    return data


def trial_words():
    data = pinned_image()
    body = struct.pack('<7I', 0x584F424D, 1, 2, 1, 2, SIZE, zlib.crc32(data))
    return struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))


def load_before():
    r = json.loads(BASELINE.read_text('utf-8'))
    path = Path(r['final_backup']).resolve()
    if (path.parent != PRIVATE.resolve() or r.get('final_outputs_off') is not True
        or r.get('final_cpu_halted') is not True
        or r.get('all_app_and_private_bytes_unchanged') is not True
        or r.get('original_start_runner_invocations') != 0
        or r.get('image_sha256') != shared.SHA):
        raise RuntimeError('Exact stopped pre-START baseline required')
    raw = path.read_bytes()
    shared.baseline(raw, (1, 2, 1, 545))
    if raw[0x40000:0x40000 + len(shared.pinned_image())] != shared.pinned_image():
        raise RuntimeError('Old latest B differs from baseline')
    return path, raw


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-inactive-b-stage', action='store_true')
    p.add_argument('--drive-12v-off', action='store_true')
    args = p.parse_args()
    data = pinned_image()
    if not args.allow_inactive_b_stage:
        print('OFFLINE PASS: exact count-only B; no hardware access')
        return
    if not args.drive_12v_off:
        p.error('Physical drive 12V OFF required')
    before_path, before = load_before()
    run = 'latest-count-only-stage-' + str(time.time_ns())
    receipt = OUTPUT / (run + '.json')
    recovered = PRIVATE / (run + '-recovered.bin')
    staged = PRIVATE / (run + '-staged.bin')
    entry = struct.unpack_from('<I', before, 0x8004)[0] & ~1
    if not 0x08008000 <= entry < 0x08040000:
        raise RuntimeError('A entry invalid')
    row = dict(pass_=False, image_sha256=SHA, image_bytes=SIZE, steps=[],
        baseline_receipt=str(BASELINE), new_b_activation=False, motor_commands=0,
        direct_metadata_write=False, force_confirm_b=False,
        drive_12v_off_user_confirmed=True)
    try:
        out = shared.debug(row, ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
            'if {[mrw 0xE000ED08] != 0x08040000} {error "Not old halted B"}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Outputs not off"}',
            *shared.full_compare_commands(PRIVATE / (run + '-before.bin'), before_path),
            'reset halt', f'bp {entry:#x} 2 hw',
            *shared.write_mailbox(shared.mailbox(3, 1, 1)),
            'reset run', 'wait_halt 25000', f'rbp {entry:#x}',
            f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not A entry"}}',
            *shared.off_commands(), *shared.off_report(),
            f'dump_image {{{recovered.as_posix()}}} 0x08000000 0x80000', 'shutdown'])
        row['recovery_outputs'] = shared.check_off(out, (0, 0x08000000, 0x08008000))
        raw = recovered.read_bytes()
        shared.baseline(raw, (1, 0, 0, 546))
        if raw[:0x7E800] != before[:0x7E800] or raw[0x7F800:] != before[0x7F800:]:
            raise RuntimeError('Recovery changed non-metadata bytes')
        row['recovered_backup'] = str(recovered)
        print('RECOVERY PASS: existing A confirmed; application not run', flush=True)
        out = shared.debug(row, ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not halted"}',
            *shared.full_compare_commands(PRIVATE / (run + '-prewrite.bin'), recovered),
            'reset halt', *shared.off_commands(),
            f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
            f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
            *shared.off_report(), 'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
            'halt', 'shutdown'])
        row['outputs'] = shared.check_off(out, (0, 0x08000000))
        actual = staged.read_bytes()
        row['comparison'] = shared.compare_flash(raw, actual, data, 'B', staged=True)
        if raw[:0x40000] != actual[:0x40000] or raw[0x78000:] != actual[0x78000:]:
            raise RuntimeError('Bytes outside inactive B changed')
        row.update(pass_=True, staged_backup=str(staged),
            staged_sha256=hashlib.sha256(actual).hexdigest(),
            all_bytes_outside_b_unchanged=True, metadata_unchanged_by_stage=True,
            cpu_reset_halted=True, generation=546)
        print('STAGE PASS: count-only B exact readback; A/private unchanged; NOT activated', flush=True)
    except BaseException as error:
        row['failure'] = str(error)
        try:
            shared.debug(row, ['init', 'halt', *shared.off_commands(), *shared.off_report(), 'shutdown'])
            row['error_cleanup_halted_off'] = True
        except BaseException as cleanup:
            row['cleanup_failure'] = str(cleanup)
        raise
    finally:
        receipt.write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
