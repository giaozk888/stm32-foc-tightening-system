"""Stage exact IRQ-source diagnostic B from healthy locked A510, never activate."""
import hashlib
import json
from pathlib import Path
import sys
import protected_feedback_fast_stage as previous
import protected_irq_dma_trace_stage as runner
from firmware_transfer_iap import image_info, fields
from zero_retest_deploy import latest_meta

OUTPUT=previous.OUTPUT
IMAGE=previous.IMAGE.parent.parent/'ProtectedIrqSourceTrace/foc2.bin'
SHA='144ad3060c358d6c7c25f9e9342bf45fd7e080f670c967fb402aad49901730e5'
FAILURE=OUTPUT/'feedback-fast-rollback-1791979526764150700.json'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='irq-source-stage'
REQUIRE_COST=REQUIRE_LATE=True
Board=previous.Board
open_port=previous.open_port

def pinned_image():
    raw=IMAGE.read_bytes()
    if len(raw)!=206520 or hashlib.sha256(raw).hexdigest()!=SHA or image_info(raw)[0]!='B':
        raise RuntimeError('Exact offline-tested IRQ source B required')
    for marker in (b'OK MOTOR TEST IRQ ORDER=G,T,R,X BODY=EXCL',
                   b'OK MOTOR TEST IRQ STATS',b'OK MOTOR TEST IRQ TOTAL',
                   b'OK MOTOR TEST LATE PATH=PAIR2',b'OK MOTOR TEST COST TRIG=POLY9_8',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'):
        if marker not in raw: raise RuntimeError('Diagnostic/protection marker missing')
    return raw

def verified_baseline(raw,evidence):
    if Path(evidence).resolve()!=FAILURE.resolve(): raise RuntimeError('Exact healthy A510 receipt required')
    r=json.loads(FAILURE.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('image_sha256')!=previous.SHA or
        r.get('motor_commands')!=0 or r.get('resets')!=0 or r.get('fallback_fault') or
        not r.get('all_app_and_private_bytes_unchanged') or
        not r.get('failed_b_not_bootable_without_new_staging') or
        r.get('fw',{}).get('GEN')!='510' or fields(r.get('status','')).get('FLT')!='0' or
        any(r.get('safe',{}).get(k)!=v for k,v in (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))) or
        raw!=previous.board_profile.previous.private_capture(r,'rollback') or
        latest_meta(raw)[2:6]!=(1,0,0,510) or latest_meta(raw)[8:10]!=(0,0)):
        raise RuntimeError('Healthy A510 output/Flash identity differs')
    return 510

if __name__=='__main__': runner.main(sys.modules[__name__])
