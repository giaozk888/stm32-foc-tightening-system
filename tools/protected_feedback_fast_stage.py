"""Exact feedback-inline B staging, only from a verified healthy A506 receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import protected_guard_fast_stage as previous
import protected_irq_dma_trace_stage as runner
import protected_irq_optimized_stage as board_profile
from firmware_transfer_iap import image_info, fields
from zero_retest_deploy import latest_meta

OUTPUT=previous.OUTPUT
IMAGE=previous.IMAGE.parent.parent/'ProtectedFeedbackFast/foc2.bin'
SHA='633a2735c3cf2e30dbc0cb19b5841b15981f9a2e08c297721ece41b751261659'
ORIGINAL=OUTPUT/'guard-fast-rollback-1791977506034036100.json'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='feedback-fast-stage'
REQUIRE_COST=True
REQUIRE_LATE=True
Board=previous.Board
open_port=previous.open_port


def pinned_image():
    raw=IMAGE.read_bytes()
    if len(raw)!=205264 or hashlib.sha256(raw).hexdigest()!=SHA or image_info(raw)[0]!='B':
        raise RuntimeError('Exact offline-tested feedback-inline B required')
    for marker in (b'OK MOTOR TEST LATE PATH=PAIR2',b'OK MOTOR TEST COST TRIG=POLY9_8',
                   b'ENC IRQ VALID=',b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'):
        if marker not in raw: raise RuntimeError('Feedback diagnostic/protection marker missing')
    return raw


def original_baseline(raw):
    r=json.loads(ORIGINAL.read_text('utf-8'))
    if (r.get('pass_') is not False or r.get('image_sha256')!=previous.SHA or
        not r.get('fallback_fault') or r.get('motor_commands')!=0 or r.get('resets')!=0 or
        not r.get('all_app_and_private_bytes_unchanged') or
        not r.get('failed_b_not_bootable_without_new_staging') or
        r.get('fw',{}).get('GEN')!='506' or
        raw!=board_profile.previous.private_capture(r,'rollback') or
        latest_meta(raw)[2:6]!=(1,0,0,506) or latest_meta(raw)[8:10]!=(0,0)):
        raise RuntimeError('Exact original locked A506 Flash required')


def verified_baseline(raw,evidence):
    path=Path(evidence).resolve()
    if path.parent!=OUTPUT.resolve() or not path.name.startswith('feedback-fast-baseline-'):
        raise RuntimeError('Dedicated healthy A506 receipt required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('mode')!='healthy-a506' or
        r.get('resets')!=1 or r.get('motor_commands')!=0 or not r.get('all_flash_unchanged') or
        not r.get('powered_motor_disconnected_user_confirmed') or
        Path(r.get('original_receipt','')).resolve()!=ORIGINAL.resolve() or
        r.get('fw',{}).get('GEN')!='506' or
        fields(r.get('status','')).get('FLT')!='0' or
        r.get('zero',{}).get('STATE')!='3' or
        r.get('zero',{}).get('N')!='4000' or
        any(r.get('safe',{}).get(k)!=v for k,v in
            (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))) or
        raw!=board_profile.previous.private_capture(r,'healthy')):
        raise RuntimeError('Healthy output-locked A506 evidence invalid')
    original_baseline(raw)
    return 506


def main():
    global FAILURE
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--baseline',type=Path,required=True)
    args,rest=parser.parse_known_args()
    FAILURE=args.baseline.resolve()
    sys.argv=[sys.argv[0],*rest]
    runner.main(sys.modules[__name__])


if __name__=='__main__': main()
