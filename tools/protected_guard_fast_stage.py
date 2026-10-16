"""Stage exact integer-guardian B from the verified A502 rollback only."""
import hashlib
import json
from pathlib import Path
import sys

import protected_pair_fast_stage as previous
import protected_irq_dma_trace_stage as runner
import protected_irq_optimized_stage as board_profile
from firmware_transfer_iap import image_info
from zero_retest_deploy import latest_meta

OUTPUT=previous.OUTPUT
IMAGE=previous.IMAGE.parent.parent/'ProtectedGuardFast/foc2.bin'
SHA='6a0957d0a54653aeea8374a062ef245676967f165cf33347c9cde3d9f93e07ef'
FAILURE=OUTPUT/'irq-compute-1791968404485719600.json'
ROLLBACK=OUTPUT/'pair-fast-rollback-1791968671765894900.json'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='guard-fast-stage'
REQUIRE_COST=True
REQUIRE_LATE=True
Board=previous.Board
open_port=previous.open_port


def pinned_image():
    raw=IMAGE.read_bytes()
    if len(raw)!=204824 or hashlib.sha256(raw).hexdigest()!=SHA or image_info(raw)[0]!='B':
        raise RuntimeError('Exact offline-tested integer-guardian B required')
    for marker in (b'OK MOTOR TEST LATE PATH=PAIR2',b'OK MOTOR TEST COST TRIG=POLY9_8',
                   b'ENC IRQ VALID=',b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'):
        if marker not in raw: raise RuntimeError('Guardian diagnostic/protection marker missing')
    return raw


def verified_baseline(raw,evidence):
    if Path(evidence).resolve()!=FAILURE.resolve():
        raise RuntimeError('Exact previous pair-fast failure required')
    failed=json.loads(FAILURE.read_text('utf-8'))
    rollback=json.loads(ROLLBACK.read_text('utf-8'))
    sample=failed.get('startup_sample',{})
    late=sample.get('late_frame',{})
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=previous.SHA or
            failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
            failed.get('failure')!='Startup fault; no reset/activation retry' or
            sample.get('state',{}).get('FLAGS')!='256' or
            sample.get('timing',{}).get('MAX_US')!='57' or
            late.get('PATH')!='PAIR2' or late.get('VALID')!='1' or late.get('US')!='57' or
            not failed.get('final_outputs_off') or failed.get('cleanup_failure')):
        raise RuntimeError('Previous exact pair-fast stopped failure invalid')
    if (rollback.get('pass_') is not True or rollback.get('image_sha256')!=previous.SHA or
            rollback.get('motor_commands')!=0 or rollback.get('resets')!=0 or
            not rollback.get('all_app_and_private_bytes_unchanged') or
            not rollback.get('failed_b_not_bootable_without_new_staging') or
            Path(rollback.get('failure_receipt','')).resolve()!=FAILURE.resolve() or
            rollback.get('fw',{}).get('GEN')!='502' or
            raw!=board_profile.previous.private_capture(rollback,'rollback') or
            latest_meta(raw)[2:6]!=(1,0,0,502) or latest_meta(raw)[8:10]!=(0,0)):
        raise RuntimeError('Exact A502 rollback/application/private bytes differ')
    return 502


if __name__=='__main__':
    runner.main(sys.modules[__name__])
