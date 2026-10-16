"""Pin the hard-off adaptive B; stage only from freshly verified healthy A514.

No image selection, fault clearing, FW END, motor command or automatic retry.
Historical private captures are compared internally and never printed.
"""
import hashlib
import json
from pathlib import Path
import sys
import protected_irq_optimized_stage as board_profile
import protected_irq_dma_trace_stage as runner
from firmware_transfer_iap import ROOT, fields, image_info
from zero_retest_deploy import latest_meta

OUTPUT=board_profile.OUTPUT
# Immutable historical candidate: rebuilding the experiment must not relabel
# the image associated with the completed A514 trial / rollback receipts.
IMAGE=ROOT/'safety_backups/adaptive-filter-optimization-20261015/pinned/adaptive-seg3-b-80411164.bin'
SHA='80411164e507cd7260d35ac05ca132d32ccb5f558c7808d69b54152a4b3bed21'
ORIGINAL=OUTPUT/'irq-source-rollback-1791982630141388000.json'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='adaptive-stage'
REQUIRE_COST=REQUIRE_LATE=True
Board=board_profile.Board
open_port=board_profile.open_port

def pinned_image():
    data=IMAGE.read_bytes()
    if len(data)!=206192 or hashlib.sha256(data).hexdigest()!=SHA or image_info(data)[0]!='B':
        raise RuntimeError('Exact offline-tested optimized adaptive B required')
    for marker in (b'OK MOTOR TEST FILTER ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1',
                   b'OK MOTOR TEST ZERO ROBUST BLOCK=5 SEGMENT=500',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
                   b'OK MOTOR TEST LATE PATH=PAIR2',b'OK MOTOR TEST COST TRIG=POLY9_8'):
        if marker not in data: raise RuntimeError('Hard-off adaptive/protection marker missing')
    return data

def original_baseline(raw):
    r=json.loads(ORIGINAL.read_text('utf-8'))
    if (r.get('pass_') is not False or
        r.get('image_sha256')!='144ad3060c358d6c7c25f9e9342bf45fd7e080f670c967fb402aad49901730e5' or
        r.get('motor_commands')!=0 or r.get('resets')!=0 or not r.get('fallback_fault') or
        not r.get('all_app_and_private_bytes_unchanged') or
        not r.get('failed_b_not_bootable_without_new_staging') or
        r.get('fw',{}).get('GEN')!='514' or
        latest_meta(raw)[2:6]!=(1,0,0,514) or latest_meta(raw)[8:10]!=(0,0) or
        raw!=board_profile.previous.private_capture(r,'rollback')):
        raise RuntimeError('Exact preserved A514/Flash identity differs')

def verified_baseline(raw,evidence):
    path=Path(evidence).resolve()
    if path.parent!=OUTPUT.resolve() or not path.name.startswith('adaptive-baseline-'):
        raise RuntimeError('Dedicated healthy adaptive baseline receipt required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('mode')!='healthy-a514' or
        r.get('resets')!=1 or r.get('motor_commands')!=0 or not r.get('all_flash_unchanged') or
        not r.get('powered_motor_disconnected_user_confirmed') or
        Path(r.get('original_receipt','')).resolve()!=ORIGINAL.resolve() or
        r.get('fw',{}).get('GEN')!='514' or fields(r.get('status','')).get('FLT')!='0' or
        r.get('zero',{}).get('STATE')!='3' or r.get('zero',{}).get('N')!='4000' or
        any(r.get('safe',{}).get(k)!=v for k,v in
            (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))) or
        raw!=board_profile.previous.private_capture(r,'healthy')):
        raise RuntimeError('Fresh healthy locked A514 receipt invalid')
    original_baseline(raw)
    return 514

def main():
    global FAILURE
    import argparse
    p=argparse.ArgumentParser(add_help=False)
    p.add_argument('--baseline',type=Path,required=True)
    args,rest=p.parse_known_args()
    FAILURE=args.baseline.resolve()
    sys.argv=[sys.argv[0],*rest]
    runner.main(sys.modules[__name__])

if __name__=='__main__': main()
