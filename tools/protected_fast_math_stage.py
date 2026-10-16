"""Pin bounded-trig B to the exact A494 automatic compute-fault rollback."""
import hashlib
import json
from pathlib import Path
import sys
import protected_irq_priority_fix_stage as previous
from firmware_transfer_iap import image_info
from zero_retest_deploy import latest_meta

OUTPUT=previous.OUTPUT
IMAGE=previous.trace.old.ROOT/'foc2_app_b/build/ProtectedFastMath/foc2.bin'
SHA='aecdf979b4530a864d00c162d6321cc5d58c4d6e4ea2e1d21b895efbc3cf956b'
FAILURE=OUTPUT/'irq-compute-1791964275522727900.json'
ROLLBACK=OUTPUT/'irq-priority-fix-rollback-1791964361329962100.json'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='fast-math-stage'
REQUIRE_COST=True
Board=previous.Board
open_port=previous.open_port

def pinned_image():
    raw=IMAGE.read_bytes()
    if len(raw)!=203176 or hashlib.sha256(raw).hexdigest()!=SHA or image_info(raw)[0]!='B':
        raise RuntimeError('Exact offline-tested bounded-trig B required')
    for marker in (b'ENC IRQ VALID=',b'OK MOTOR TEST COST TRIG=POLY9_8',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'):
        if marker not in raw: raise RuntimeError('Bounded-trig diagnostics/protection absent')
    return raw

def verified_baseline(raw,evidence):
    if Path(evidence).resolve()!=FAILURE.resolve():
        raise RuntimeError('Exact prior compute-late receipt required')
    failed=json.loads(FAILURE.read_text('utf-8'))
    rollback=json.loads(ROLLBACK.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=previous.SHA or
        failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
        failed.get('failure')!='Startup fault; no reset/activation retry' or
        failed.get('startup_sample',{}).get('state',{}).get('FLAGS')!='256' or
        failed.get('startup_sample',{}).get('timing',{}).get('MAX_US')!='65' or
        not failed.get('final_outputs_off') or failed.get('cleanup_failure')):
        raise RuntimeError('Prior exact compute-late failure invalid')
    if (rollback.get('pass_') is not True or rollback.get('motor_commands')!=0 or
        rollback.get('resets')!=0 or not rollback.get('all_app_and_private_bytes_unchanged') or
        Path(rollback.get('failure_receipt','')).resolve()!=FAILURE.resolve() or
        rollback.get('fw',{}).get('GEN')!='494' or
        raw!=previous.trace.old.previous.private_capture(rollback,'rollback') or
        latest_meta(raw)[2:6]!=(1,0,0,494) or latest_meta(raw)[8:10]!=(0,0)):
        raise RuntimeError('Current exact A494 rollback/application/private bytes differ')
    return 494

if __name__=='__main__': previous.trace.main(sys.modules[__name__])
