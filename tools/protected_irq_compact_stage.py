"""Pin compact hard-off B; exact proved A530 only; staging never activates."""
import hashlib
import json
from pathlib import Path
import sys
import protected_adaptive_ram_stage as previous
import protected_irq_dma_trace_stage as runner
from protected_adaptive_stage import board_profile
from firmware_transfer_iap import ROOT,image_info
from zero_retest_deploy import latest_meta

OUTPUT=previous.OUTPUT
ORIGINAL=OUTPUT/'adaptive-ram-rollback-1792041472791821400.json'
FAILURE=ORIGINAL
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='irq-compact-stage'
ROLLBACK_PREFIX='irq-compact-rollback'
GENERATION=530
IMAGE=ROOT/'foc2_app_b/build/ProtectedIrqCompact/foc2.bin'
SHA='46eb9b65e0494a0fccac3dfd1c4b0935f3882c73e53bfb2f1c9cb2b3e270af73'
Board,open_port=previous.Board,previous.open_port
REQUIRE_COST=REQUIRE_LATE=True
OBSERVE_SECONDS=30.0

def pinned_image():
    data=IMAGE.read_bytes()
    if len(data)!=207196 or hashlib.sha256(data).hexdigest()!=SHA or image_info(data)[0]!='B':
        raise RuntimeError('Exact offline-tested compact hard-off B required')
    for marker in (b'MOTOR TEST COMPACT ENABLED=1 HARD_OFF=1 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50',
        b'MOTOR TEST RAM ENABLED=1 HARD_OFF=1 DEADLINE_US=50',
        b'MOTOR TEST FILTER ADAPT=1 HARD_OFF=1',
        b'MAX=OFF SEG_MAX=OFF SEG_OUTLIERS=%lu FLAGS=%u HARD_OFF=1',
        b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
        b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000',
        b'MOTOR TEST LATE PATH=PAIR2',b'MOTOR TEST COST TRIG=POLY9_8'):
        if marker not in data: raise RuntimeError('Compact identity/retained protection marker absent')
    return data

def verified_baseline(raw,evidence):
    path=Path(evidence).resolve()
    if path!=ORIGINAL.resolve(): raise RuntimeError('Exact proved A530 fallback receipt required')
    r=json.loads(path.read_text('utf-8'))
    if (r.get('pass_') is not True or r.get('image_sha256')!=previous.SHA or
        r.get('resets')!=0 or r.get('motor_commands')!=0 or
        r.get('fallback_healthy') is not True or
        not r.get('all_app_and_private_bytes_unchanged') or
        not r.get('failed_b_not_bootable_without_new_staging') or
        r.get('fw',{}).get('GEN')!=str(GENERATION) or
        latest_meta(raw)[2:6]!=(1,0,0,GENERATION) or latest_meta(raw)[8:10]!=(0,0) or
        raw!=board_profile.previous.private_capture(r,'rollback')):
        raise RuntimeError('Current A530 Flash differs from proven locked fallback')
    return GENERATION

def main(): runner.main(sys.modules[__name__])
if __name__=='__main__': main()
