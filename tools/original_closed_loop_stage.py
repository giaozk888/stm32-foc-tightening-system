"""Stage the exact October 8 normal B image; never activate or start a motor.

Requires drive power physically OFF. Preserve a full Flash backup, A536,
bootloader and all data. Leave the CPU reset/halted, with SD/PWM disabled.
No boot metadata, trial mailbox, protection or recipe edits are permitted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from firmware_transfer_iap import ROOT, image_info
from protected_irq_optimized_stage import Board, open_port
from tighten_synthetic_swd_recovery import OCD, SCRIPTS, SN, latest_meta
from zero_retest_deploy import compare_flash, DiagnosticUart, require_confirmed

IMAGE = ROOT / 'foc2_app_b/build/PoweredSpeedBounded20261008/foc2.bin'
SHA = '8b57f03e359f532338361b5fa8e53540d4afa829bb3acf3793e24f0b9b9a604c'
A_SHA = '493ff25e02feacd886f8f97f2eb91c7b64338fdea3cb517313035f3e6f52b875'
OUTPUT = ROOT / 'safety_backups/protected-closed-loop-20261014'
BASELINE = OUTPUT / 'compact-motor-trial-1792045417187329600.json'


def validate_before(raw, baseline):
    if len(raw) != 0x80000 or raw != baseline:
        raise RuntimeError('Live Flash differs from preserved final A536 receipt')
    if latest_meta(raw)[2:6] != (1, 0, 0, 536):
        raise RuntimeError('Only confirmed A536, no pending trial admitted')
    if hashlib.sha256(raw[0x8000:0x8000 + 207972]).hexdigest() != A_SHA:
        raise RuntimeError('A536 fallback image mismatch')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-inactive-b-stage', action='store_true')
    p.add_argument('--drive-12v-off', action='store_true')
    args = p.parse_args()
    image = IMAGE.read_bytes()
    if len(image) != 199056 or hashlib.sha256(image).hexdigest() != SHA or image_info(image)[0] != 'B':
        raise RuntimeError('Pinned original B image mismatch')
    if not (args.allow_inactive_b_stage and args.drive_12v_off):
        print('OFFLINE PASS: exact original B; no hardware operation')
        return
    receipt = json.loads(BASELINE.read_text('utf-8'))
    baseline_path = Path(receipt['final_backup']).resolve()
    if baseline_path.parent != (OUTPUT / 'private').resolve():
        raise RuntimeError('Baseline private capture path mismatch')
    baseline = baseline_path.read_bytes()
    run = 'original-b-stage-' + str(time.time_ns())
    record = dict(image=str(IMAGE), image_sha256=SHA, image_size=len(image),
                  pass_=False, steps=[], activation=False, motor_commands=0,
                  direct_metadata_write=False, trial_mailbox_write=False)
    result_path = OUTPUT / (run + '.json')
    board = Board(record, run)
    port = None
    try:
        port = open_port()
        uart = DiagnosticUart(port)
        for command in ('FW STATUS', 'ANALOG SAFE STATUS', 'STATUS'):
            line = uart.query(command)
            record[command] = line
            print(line, flush=True)
        require_confirmed(record['FW STATUS'], 'A')
        board.outputs('A')
        before = board.capture('before')
        validate_before(before, baseline)
        port.close()
        staged_path = OUTPUT / 'private' / (run + '-staged.bin')
        commands = [
            'init', 'halt', 'reset halt',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted in bootloader"}',
            'mmw 0x4002104C 0x4 0', 'mww 0x48000818 0x00400000',
            'mmw 0x48000800 0x1000 0x2000', 'mmw 0x40021060 0x800 0',
            'mww 0x48000818 0x00400000', 'mww 0x40012C20 0',
            'mmw 0x40012C44 0 0xC000', 'mmw 0x40012C00 0 1',
            f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
            f'verify_image {{{IMAGE.as_posix()}}} 0x08040000 bin',
            f'dump_image {{{staged_path.as_posix()}}} 0x08000000 0x80000',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Output off proof failed"}',
            'halt', 'shutdown',
        ]
        invocation = [OCD, '-s', SCRIPTS, '-f', 'interface/stlink.cfg', '-f', 'target/stm32g4x.cfg',
                      '-c', 'gdb_port disabled; tcl_port disabled; telnet_port disabled; adapter serial ' + SN +
                      '; adapter speed 1000; ' + '; '.join(commands)]
        proc = subprocess.run(invocation, capture_output=True, text=True, errors='replace', timeout=60)
        output = proc.stdout + proc.stderr
        record['steps'].append(dict(tool='OpenOCD', code=proc.returncode, output=output))
        if proc.returncode or 'Error:' in output:
            raise RuntimeError('Stage failed; no resume/reset/retry. See saved receipt.')
        actual = staged_path.read_bytes()
        record['staged_backup'] = str(staged_path)
        record['comparison'] = compare_flash(before, actual, image, 'B', staged=True)
        if before[:0x40000] != actual[:0x40000] or before[0x78000:] != actual[0x78000:]:
            raise RuntimeError('Bytes outside inactive B changed')
        record.update(pass_=True, cpu_reset_halted=True, outputs_off=True,
                      metadata_unchanged=True, activation_requires_normal_bootloader_trial=True)
        print('STAGE PASS: original B exact readback; A536/data/metadata unchanged; CPU HALTED; NO activation.', flush=True)
    except BaseException as error:
        record['failure'] = str(error)
        raise
    finally:
        if port is not None and port.is_open:
            port.close()
        result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(result_path), flush=True)


if __name__ == '__main__':
    main()
