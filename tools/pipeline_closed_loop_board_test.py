"""Exact protected pipeline candidate: offline verification or inactive-A stage.

This module has no activation or motion mode. It reuses only the existing
whole-Flash/erase-page transaction, not a hard-OFF runner's acceptance gates.
The actuating image is identified as HARD_OFF=0, never relabelled hard-OFF.
"""
import argparse
import hashlib
import json
import time

import rc_deferred_shadow_board_test as tx
from firmware_transfer_iap import image_info
from original_closed_loop_trial import emergency_off

ROOT, OUTPUT, PRIVATE = tx.ROOT, tx.OUTPUT, tx.PRIVATE
IMAGE = ROOT/'foc2_app_a/build/ClosedLoopIntegration/ProtectedPipelineClosedLoop/foc2.bin'
ELF = IMAGE.with_suffix('.elf')
SHA = 'b4d2368220699e6cf792b0a7032c52e3c74cb112351133363f97bcc4706cdd3e'
ELF_SHA = '5172cdd735e6152a3c9af38d5c1fd6840152d076f8b2388c1d0ee60fdb635477'
SIZE = 228940
PREFIX = 'protected-pipeline-'
BASE_RECEIPT = OUTPUT/'encoder-health-restore-1792225057329032900.json'
BASE_SHA = '270e1e887551c61cdc9826e242b017dfb66a6d86c7353a0780f9f2c9f00cbc2b'
BASE_META = (1112493908,3,2,0,0,615,228964,3734682205,210916,453748590,0,3170141304)
B_SHA = '9fd54166df782cce3e737ecfebe67bc4aff8f15a005fca1f1136c91bb8786f44'
MARKER = b'NAME=PROTECTED_PIPELINE_CLOSED_LOOP HARD_OFF=0 FSM=ORIGINAL PIPELINE=1 LOCAL=1 RPM=20 LEASE_US=400000 QUALIFIED=0'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_build(data, elf, receipt):
    if (len(data) != SIZE or digest(data) != SHA or digest(elf) != ELF_SHA or
            image_info(data)[0] != 'A' or MARKER not in data):
        raise ValueError('Exact protected actuating A BIN/ELF identity required')
    if (receipt.get('offline_only') is not True or receipt.get('hardware_access') is not False or
            receipt.get('motor_started') is not False or receipt.get('boot_selection_changed') is not False or
            receipt.get('test_count') != 168 or receipt.get('historical_bin_unchanged_count') != 16 or
            not any(b.get('app') == 'foc2_app_a' and b.get('profile') == 'ProtectedPipelineClosedLoop' and
                    b.get('bin_sha256') == SHA and b.get('elf_sha256') == ELF_SHA
                    for b in receipt.get('builds', [])) or
            not any(t.get('module') == 'test_pipeline_closed_loop' and t.get('passed') == 6
                    for t in receipt.get('tests', []))):
        raise ValueError('Matching successful candidate offline receipt required')


def image():
    data = IMAGE.read_bytes()
    receipt = json.loads((ROOT/'tests/foc_adaptive_build/pipeline_closed_loop_evidence/receipt.json').read_text())
    verify_build(data, ELF.read_bytes(), receipt)
    return data


def configure_transaction():
    # Only stage/byte-comparison helpers are reused. No monkey-patched trial,
    # output-enable, health gate, or old hard-OFF schema is executed.
    for name in ('IMAGE','SHA','SIZE','PREFIX','BASE_RECEIPT','BASE_SHA','BASE_META','B_SHA'):
        setattr(tx, name, globals()[name])
    tx.image = image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-inactive-a', action='store_true')
    parser.add_argument('--drive-12v-off', action='store_true')
    args = parser.parse_args()
    if args.stage_inactive_a and not args.drive_12v_off:
        parser.error('Actual drive 12 V OFF required before any device operation')
    data = image()
    if not args.stage_inactive_a:
        print('OFFLINE PASS: exact protected candidate; no devices/private data accessed')
        return 0
    configure_transaction()
    # Validate the immutable baseline before attempting any device mutation.
    tx.baseline()
    run = PREFIX+'stage-'+str(time.time_ns())
    row = dict(pass_=False, mode='stage', image_sha256=SHA, elf_sha256=ELF_SHA,
        image_bytes=SIZE, steps=[], hardware_attempted=False, programming_attempted=False,
        motor_commands=0, activation=False, automatic_retry=False, force_confirmation=False,
        direct_metadata_write=False, drive_12v_off_user_confirmed=True,
        motor_closed_loop_verified=False)
    try:
        tx.stage(row, run, data)
        # The reused transaction has historical human-readable labels. The
        # cryptographic receipt and this explicit identity describe this run.
        print('PROTECTED PIPELINE A STAGED: confirmed B615 retained; not activated; START=0', flush=True)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        if row.get('programming_attempted') and not row.get('final_cpu_halted'):
            try:
                emergency_off(row, PRIVATE/(run+'-cleanup.bin'))
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
        print('STAGE FAILED: '+str(error), flush=True)
    finally:
        path = OUTPUT/(run+'.json')
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(path), flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
