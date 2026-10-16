"""One read-only verification after the recorded stage CRC-debug error.

No reset, Flash writes, resume, mailbox changes or motor commands. Preserve
the failed receipt and report the independent full-byte verification separately.
"""
import hashlib
import json
import time
from pathlib import Path

import original_closed_loop_updated_stage as stage

FAILED = stage.OUTPUT / 'original-updated-1792049819195370800.json'
INSPECTION = stage.OUTPUT / 'original-updated-1792049742928831300.json'


def main():
    failed = json.loads(FAILED.read_text('utf-8'))
    inspection = json.loads(INSPECTION.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256') != stage.SHA
            or failed.get('activation') is not False or failed.get('motor_commands') != 0
            or 'error executing cortex_m crc algorithm' not in failed['steps'][0]['output']
            or inspection.get('pass_') is not True):
        raise RuntimeError('Exact non-activated stage error and inspection required')
    before_path = Path(inspection['before_backup']).resolve()
    if before_path.parent != stage.PRIVATE.resolve():
        raise RuntimeError('Private baseline path mismatch')
    before = before_path.read_bytes()
    stage.validate_baseline(before)
    if hashlib.sha256(before).hexdigest() != inspection['before_sha256']:
        raise RuntimeError('Baseline changed')
    run = 'original-updated-readback-' + str(time.time_ns())
    path = stage.PRIVATE / (run + '.bin')
    receipt = stage.OUTPUT / (run + '.json')
    row = dict(pass_=False, mode='independent-readback-only', failed_stage=str(FAILED),
               inspection=str(INSPECTION), steps=[], flash_writes=0, resets=0,
               activation=False, motor_commands=0, image_sha256=stage.SHA)
    try:
        output = stage.debug(row, ['init',
            'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not already halted"}',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted in bootloader"}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20] || [mrw 0x40012C00] & 1} {error "Output not off"}',
            *stage.off_report(), f'dump_image {{{path.as_posix()}}} 0x08000000 0x80000',
            'shutdown'])
        row['outputs'] = stage.check_off(output, (0, 0x08000000))
        actual = path.read_bytes()
        row['comparison'] = stage.compare_flash(before, actual, stage.pinned_image(), 'B', staged=True)
        if before[:0x40000] != actual[:0x40000] or before[0x78000:] != actual[0x78000:]:
            raise RuntimeError('Bytes outside inactive B changed')
        row.update(pass_=True, readback_backup=str(path), metadata_unchanged=True,
                   all_bytes_outside_b_unchanged=True, cpu_halted=True)
        print('READBACK PASS: updated-original B exact; A/bootloader/private/metadata unchanged; SD/PWM off; CPU HALTED; NOT ACTIVATED')
    except BaseException as error:
        row['failure'] = str(error)
        raise
    finally:
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt))


if __name__ == '__main__':
    main()
