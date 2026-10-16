"""Pinned updated-original B staging ONLY; no activation, resume or motion.

Inspect requires an already halted, output-off A. Stage verifies that exact
full capture before reset/halt and writes only inactive B. Full Flash backups
remain inside the established private evidence directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from firmware_transfer_iap import ROOT, image_info
from tighten_synthetic_swd_recovery import OCD, SCRIPTS, SN, latest_meta
from zero_retest_deploy import compare_flash

OUTPUT = ROOT / 'safety_backups/protected-closed-loop-20261014'
PRIVATE = OUTPUT / 'private'
IMAGE = ROOT / 'foc2_app_b/build/OriginalClosedLoopUpdated/foc2.bin'
SHA = '78eb75ceb4bb87c256af67e3081ad4300dda98cecf2a016386539cc46b22cfe7'
A_SHA = '493ff25e02feacd886f8f97f2eb91c7b64338fdea3cb517313035f3e6f52b875'


def pinned_image():
    data = IMAGE.read_bytes()
    if (len(data) != 200360 or hashlib.sha256(data).hexdigest() != SHA
            or image_info(data)[0] != 'B'):
        raise RuntimeError('Exact updated-original B required')
    for marker in (b'ORIGINAL_UPDATED_20261015', b'START=ORIGINAL QUALIFIED=0',
                   b'Phase trip      : 4.0A; powered validation pending'):
        if marker not in data:
            raise RuntimeError('Updated-original identity missing')
    return data


def validate_baseline(raw):
    if len(raw) != 0x80000:
        raise RuntimeError('Full Flash backup required')
    meta = latest_meta(raw)
    if meta[2:5] != (1, 0, 0) or meta[8:10] != (0, 0):
        raise RuntimeError('Require confirmed A, no pending or attempted trial')
    if hashlib.sha256(raw[0x8000:0x8000 + 207972]).hexdigest() != A_SHA:
        raise RuntimeError('Exact preserved A fallback mismatch')
    return meta


def check_off(output, vtor):
    names = ('VTOR', 'DHCSR', 'SD', 'BDTR', 'CCER')
    regs = {name: int(value, 16) for name, value in
            re.findall(r'(?m)^(VTOR|DHCSR|SD|BDTR|CCER)=(0x[0-9a-fA-F]+)\s*$', output)}
    if (set(regs) != set(names) or regs['VTOR'] not in vtor
            or not regs['DHCSR'] & 0x20000 or regs['SD'] & 0x40
            or regs['BDTR'] & 0xC000 or regs['CCER']):
        raise RuntimeError('Halted/off output proof incomplete')
    return regs


def off_report():
    return ['echo VTOR=[mrw 0xE000ED08]', 'echo DHCSR=[mrw 0xE000EDF0]',
            'echo SD=[mrw 0x48000814]', 'echo BDTR=[mrw 0x40012C44]',
            'echo CCER=[mrw 0x40012C20]']


def debug(record, commands):
    result = subprocess.run([OCD, '-s', SCRIPTS, '-f', 'interface/stlink.cfg',
        '-f', 'target/stm32g4x.cfg', '-c',
        'gdb_port disabled; tcl_port disabled; telnet_port disabled; adapter serial '
        + SN + '; adapter speed 1000; ' + '; '.join(commands)],
        capture_output=True, text=True, errors='replace', timeout=60)
    output = result.stdout + result.stderr
    record['steps'].append(dict(code=result.returncode, output=output))
    if result.returncode or 'Error:' in output:
        raise RuntimeError('Debug operation failed; no retry, resume or activation')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--inspect-halted-a', action='store_true')
    modes.add_argument('--stage-from-inspection', type=Path)
    parser.add_argument('--drive-12v-off', action='store_true')
    parser.add_argument('--allow-inactive-b-stage', action='store_true')
    args = parser.parse_args()
    data = pinned_image()
    if not args.drive_12v_off:
        parser.error('Drive 12 V must be physically off')
    if args.stage_from_inspection and not args.allow_inactive_b_stage:
        parser.error('Inactive-B stage authorization required')
    run = 'original-updated-' + str(time.time_ns())
    receipt = OUTPUT / (run + '.json')
    row = dict(pass_=False, image_sha256=SHA, image_bytes=len(data), steps=[],
               activation=False, motor_commands=0, direct_metadata_write=False,
               trial_mailbox_write=False, drive_12v_off_user_confirmed=True)
    try:
        if args.inspect_halted_a:
            row['mode'] = 'inspect'
            path = PRIVATE / (run + '-before.bin')
            output = debug(row, ['init',
                'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU not already halted"}',
                'if {[mrw 0xE000ED08] != 0x08008000} {error "Not A"}',
                'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Output not off"}',
                *off_report(), f'dump_image {{{path.as_posix()}}} 0x08000000 0x80000',
                'shutdown'])
            row['outputs'] = check_off(output, (0x08008000,))
            raw = path.read_bytes()
            meta = validate_baseline(raw)
            row.update(before_backup=str(path), before_sha256=hashlib.sha256(raw).hexdigest(),
                       generation=meta[5], confirmed_slot='A', pending_slot='-')
        else:
            row['mode'] = 'stage'
            source = args.stage_from_inspection.resolve()
            if source.parent != OUTPUT.resolve():
                raise RuntimeError('Inspection receipt outside evidence directory')
            prior = json.loads(source.read_text('utf-8'))
            if (prior.get('mode') != 'inspect' or prior.get('pass_') is not True
                    or prior.get('image_sha256') != SHA):
                raise RuntimeError('Verified current inspection required')
            before_path = Path(prior['before_backup']).resolve()
            if before_path.parent != PRIVATE.resolve():
                raise RuntimeError('Private baseline path mismatch')
            before = before_path.read_bytes()
            validate_baseline(before)
            if hashlib.sha256(before).hexdigest() != prior['before_sha256']:
                raise RuntimeError('Baseline changed')
            staged = PRIVATE / (run + '-staged.bin')
            live_before = PRIVATE / (run + '-live-before.bin')
            output = debug(row, ['init',
                'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "CPU no longer halted"}',
                'if {[mrw 0xE000ED08] != 0x08008000} {error "Not A"}',
                'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C20]} {error "Output not off"}',
                f'dump_image {{{live_before.as_posix()}}} 0x08000000 0x80000',
                'proc task_readbin {path} {set handle [open $path rb]; set contents [read $handle]; close $handle; return $contents}',
                f'if {{[task_readbin {{{live_before.as_posix()}}}] ne [task_readbin {{{before_path.as_posix()}}}]}} {{error "Live Flash changed"}}',
                'reset halt',
                'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted in bootloader"}',
                'mmw 0x4002104C 0x4 0', 'mww 0x48000818 0x00400000',
                'mmw 0x48000800 0x1000 0x2000', 'mmw 0x40021060 0x800 0',
                'mww 0x40012C20 0', 'mmw 0x40012C44 0 0xC000',
                'mmw 0x40012C00 0 1',
                f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin',
                f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
                *off_report(),
                'if {[mrw 0x40012C00] & 1} {error "Timer not stopped"}',
                'halt', 'shutdown'])
            row['outputs'] = check_off(output, (0, 0x08000000))
            actual = staged.read_bytes()
            row['comparison'] = compare_flash(before, actual, data, 'B', staged=True)
            if before[:0x40000] != actual[:0x40000] or before[0x78000:] != actual[0x78000:]:
                raise RuntimeError('Bytes outside inactive B changed')
            row.update(inspection=str(source), before_backup=str(before_path),
                       staged_backup=str(staged), metadata_unchanged=True,
                       all_bytes_outside_b_unchanged=True, cpu_reset_halted=True)
        row['pass_'] = True
        print('PASS: ' + row['mode'] + '; no activation or motor command', flush=True)
        if row['mode'] == 'inspect':
            print('Confirmed A generation=' + str(row['generation']) + '; fallback exact; output off')
    except BaseException as error:
        row['failure'] = str(error)
        raise
    finally:
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt), flush=True)


if __name__ == '__main__':
    main()
