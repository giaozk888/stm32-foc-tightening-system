"""Stage one exact hard-off B from the previously proved A522 fallback.

No FW END, power enable, fault clear, motor command, or host retry.
Full Flash comparisons and backups stay in the restricted private directory.
"""
import hashlib
import json
import sys
from pathlib import Path

import protected_adaptive_segoff_stage as previous
import protected_irq_dma_trace_stage as runner
from firmware_transfer_iap import ROOT,image_info
from zero_retest_deploy import latest_meta

OUTPUT=previous.OUTPUT
ORIGINAL=OUTPUT/'adaptive-segoff-rollback-1792036650782142300.json'
FAILURE=ORIGINAL
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='adaptive-noquota-stage'
ROLLBACK_PREFIX='adaptive-noquota-rollback'
GENERATION=522
IMAGE=ROOT/'foc2_app_b/build/ProtectedAdaptiveNoZeroQuota/foc2.bin'
SHA='cea42a3732029abf9b8f0ccd3691cb8d266ef5459242ca2ffd496fe997236f06'
Board=previous.Board
open_port=previous.open_port
REQUIRE_COST=REQUIRE_LATE=True

def pinned_image():
    data=IMAGE.read_bytes()
    if len(data)!=206184 or hashlib.sha256(data).hexdigest()!=SHA or image_info(data)[0]!='B':
        raise RuntimeError('Exact offline-tested hard-off no-quota B required')
    for marker in (b'MOTOR TEST FILTER ADAPT=1 HARD_OFF=1',
                   b'MAX=OFF SEG_MAX=OFF SEG_OUTLIERS=%lu FLAGS=%u HARD_OFF=1',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
                   b'MOTOR TEST LATE PATH=PAIR2',b'MOTOR TEST COST TRIG=POLY9_8'):
        if marker not in data: raise RuntimeError('Hard-off/retained protection marker absent')
    return data

def verified_baseline(raw,evidence):
    path=Path(evidence).resolve()
    if path!=ORIGINAL.resolve(): raise RuntimeError('Exact A522 fallback receipt required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('image_sha256')!=previous.SHA or
        r.get('resets')!=0 or r.get('motor_commands')!=0 or
        r.get('fallback_healthy') is not True or
        not r.get('all_app_and_private_bytes_unchanged') or
        not r.get('failed_b_not_bootable_without_new_staging') or
        r.get('fw',{}).get('GEN')!=str(GENERATION) or
        latest_meta(raw)[2:6]!=(1,0,0,GENERATION) or latest_meta(raw)[8:10]!=(0,0) or
        raw!=previous.board_profile.previous.private_capture(r,'rollback')):
        raise RuntimeError('Current A522 Flash differs from proven fallback')
    return GENERATION

def main():
    runner.main(sys.modules[__name__])

if __name__=='__main__': main()
