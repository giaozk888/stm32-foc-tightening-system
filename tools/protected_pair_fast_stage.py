"""Stage exact pair-fast B from the verified A498 automatic rollback only."""
import hashlib
import json
from pathlib import Path
import sys

import protected_fast_math_stage as previous
from firmware_transfer_iap import image_info
from zero_retest_deploy import latest_meta

OUTPUT=previous.OUTPUT
IMAGE=previous.previous.trace.old.ROOT/'foc2_app_b/build/ProtectedPairFast/foc2.bin'
SHA='a8117c7fda8b10887b79b6dd070a044f29d97a0e2776db5a18cdfb9cf60e80ec'
FAILURE=OUTPUT/'irq-compute-1791965830441873200.json'
ROLLBACK=OUTPUT/'fast-math-rollback-1791966101443919300.json'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='pair-fast-stage'
REQUIRE_COST=True
REQUIRE_LATE=True
Board=previous.Board
open_port=previous.open_port


def pinned_image():
    raw=IMAGE.read_bytes()
    if len(raw)!=204792 or hashlib.sha256(raw).hexdigest()!=SHA or image_info(raw)[0]!='B':
        raise RuntimeError('Exact offline-tested pair-fast B required')
    for marker in (b'OK MOTOR TEST LATE PATH=PAIR2',b'OK MOTOR TEST COST TRIG=POLY9_8',
                   b'ENC IRQ VALID=',b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'):
        if marker not in raw:
            raise RuntimeError('Pair-fast diagnostic/protection marker missing')
    return raw


def verified_baseline(raw,evidence):
    if Path(evidence).resolve()!=FAILURE.resolve():
        raise RuntimeError('Exact previous fast-math failure required')
    failed=json.loads(FAILURE.read_text('utf-8'))
    rollback=json.loads(ROLLBACK.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=previous.SHA or
            failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
            failed.get('failure')!='Startup fault; no reset/activation retry' or
            failed.get('startup_sample',{}).get('state',{}).get('FLAGS')!='256' or
            failed.get('startup_sample',{}).get('timing',{}).get('MAX_US')!='65' or
            not failed.get('final_outputs_off') or failed.get('cleanup_failure')):
        raise RuntimeError('Previous exact fast-math stopped failure invalid')
    if (rollback.get('pass_') is not True or rollback.get('image_sha256')!=previous.SHA or
            rollback.get('motor_commands')!=0 or rollback.get('resets')!=0 or
            not rollback.get('all_app_and_private_bytes_unchanged') or
            not rollback.get('failed_b_not_bootable_without_new_staging') or
            Path(rollback.get('failure_receipt','')).resolve()!=FAILURE.resolve() or
            rollback.get('fw',{}).get('GEN')!='498' or
            raw!=previous.previous.trace.old.previous.private_capture(rollback,'rollback') or
            latest_meta(raw)[2:6]!=(1,0,0,498) or latest_meta(raw)[8:10]!=(0,0)):
        raise RuntimeError('Exact A498 rollback/application/private bytes differ')
    return 498


if __name__=='__main__':
    previous.previous.trace.main(sys.modules[__name__])
