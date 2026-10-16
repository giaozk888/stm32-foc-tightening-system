"""Exact SEG_MAX=OFF hard-off B, only from newly healthy preserved A518."""
import hashlib
import json
from pathlib import Path
import sys
import protected_adaptive_stage as historical
from firmware_transfer_iap import ROOT,fields,image_info
from zero_retest_deploy import latest_meta

board_profile=historical.board_profile
Board,open_port=historical.Board,historical.open_port
OUTPUT=historical.OUTPUT
ORIGINAL=OUTPUT/'adaptive-rollback-1792035174150795400.json'
GENERATION=518
BASELINE_PREFIX='adaptive-segoff-baseline'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='adaptive-segoff-stage'
ROLLBACK_PREFIX='adaptive-segoff-rollback'
IMAGE=ROOT/'foc2_app_b/build/ProtectedAdaptiveFilter/foc2.bin'
SHA='b966586c13cae2340c120e9ada13123be2e763f432bde516b594ee48302cd31b'
REQUIRE_COST=REQUIRE_LATE=True

def pinned_image():
    data=IMAGE.read_bytes()
    if len(data)!=206192 or hashlib.sha256(data).hexdigest()!=SHA or image_info(data)[0]!='B':
        raise RuntimeError('Exact offline-tested segment-off B required')
    for marker in (b'OK MOTOR TEST FILTER ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1',
        b'MAX=20 SEG_MAX=OFF SEG_OUTLIERS=%lu FLAGS=%u HARD_OFF=1',
        b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
        b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
        b'OK MOTOR TEST LATE PATH=PAIR2',b'OK MOTOR TEST COST TRIG=POLY9_8'):
        if marker not in data: raise RuntimeError('Exact hard-off/retained protection marker absent')
    return data

def original_baseline(raw):
    r=json.loads(ORIGINAL.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('fallback_healthy') is not False or
        r.get('image_sha256')!=historical.SHA or r.get('resets')!=0 or r.get('motor_commands')!=0 or
        not r.get('all_app_and_private_bytes_unchanged') or
        not r.get('failed_b_not_bootable_without_new_staging') or
        r.get('fw',{}).get('GEN')!='518' or latest_meta(raw)[2:6]!=(1,0,0,518) or
        latest_meta(raw)[8:10]!=(0,0) or
        raw!=board_profile.previous.private_capture(r,'rollback')):
        raise RuntimeError('Exact preserved A518 rollback/Flash required')

def expected_fault(row):
    if (fields(row['status']).get('FLT')!='1' or row['zero'].get('STATE')!='3' or
        row['protection'].get('REASON')!='9' or row['protection'].get('FLAGS')!='0' or
        row['fault'].get('SEQ')!='297111'):
        raise RuntimeError('Preserved A518 repair-budget fault absent; no reset')

def verified_baseline(raw,evidence):
    path=Path(evidence).resolve()
    if path.parent!=OUTPUT.resolve() or not path.name.startswith(BASELINE_PREFIX+'-'):
        raise RuntimeError('Dedicated healthy A518 baseline receipt required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('mode')!='healthy-a518' or r.get('resets')!=1 or
        r.get('motor_commands')!=0 or not r.get('all_flash_unchanged') or
        not r.get('powered_motor_disconnected_user_confirmed') or
        Path(r.get('original_receipt','')).resolve()!=ORIGINAL.resolve() or
        r.get('fw',{}).get('GEN')!='518' or fields(r.get('status','')).get('FLT')!='0' or
        r.get('zero',{}).get('STATE')!='3' or r.get('zero',{}).get('N')!='4000' or
        any(r.get('safe',{}).get(k)!=v for k,v in
            (('LATCHED','1'),('SD','0'),('MOE','0'),('FOC','0'))) or
        raw!=board_profile.previous.private_capture(r,'healthy')):
        raise RuntimeError('Fresh healthy locked A518 receipt invalid')
    original_baseline(raw)
    return GENERATION

def main():
    global FAILURE
    import argparse
    p=argparse.ArgumentParser(add_help=False)
    p.add_argument('--baseline',type=Path,required=True)
    args,rest=p.parse_known_args()
    FAILURE=args.baseline.resolve(); sys.argv=[sys.argv[0],*rest]
    historical.runner.main(sys.modules[__name__])

if __name__=='__main__': main()
