"""Pin priority-fix B to the exact A490 automatic timeout rollback."""
import hashlib
import json
from pathlib import Path
import sys

import protected_irq_dma_trace_stage as trace
from firmware_transfer_iap import image_info
from zero_retest_deploy import latest_meta

OUTPUT=trace.OUTPUT
IMAGE=trace.old.ROOT/'foc2_app_b/build/ProtectedIrqPriorityFix/foc2.bin'
SHA='8dd4e2a61c1dbcefd7d3af71b3bb51444ec2ac25961a47672c6e136d4d9102be'
FAILURE=OUTPUT/'irq-compute-1791960118513595600.json'
BASELINE_KEY='rollback_evidence'
STAGE_PREFIX='irq-priority-fix-stage'
Board=trace.Board
open_port=trace.open_port

def pinned_image():
    raw=IMAGE.read_bytes()
    if len(raw)!=206560 or hashlib.sha256(raw).hexdigest()!=SHA or image_info(raw)[0]!='B':
        raise RuntimeError('Exact offline-tested priority-fix B required')
    for marker in (b'ENC IRQ VALID=',b'ENC SNAP VALID=',
                   b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                   b'LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'):
        if marker not in raw: raise RuntimeError('Priority-fix diagnostic/protection marker absent')
    return raw

def verified_baseline(raw,evidence):
    path=Path(evidence).resolve()
    if path!=FAILURE.resolve(): raise RuntimeError('Exact DMA trace timeout receipt required')
    failed=json.loads(path.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256')!=trace.SHA or
        failed.get('host_trial_commits')!=1 or failed.get('host_motor_commands')!=0 or
        failed.get('failure')!='Startup fault; no reset/activation retry' or
        failed.get('startup_encoder_dma',{}).get('TIMEOUT')!='1' or
        failed.get('startup_encoder_snapshot',{}).get('PH')!='4' or
        not failed.get('final_outputs_off') or failed.get('cleanup_failure')):
        raise RuntimeError('Prior exact HOLD timeout receipt invalid')
    before=trace.old.previous.private_capture(failed,'before_trial')
    if (raw[:0x7E800]!=before[:0x7E800] or raw[0x7F800:]!=before[0x7F800:] or
        latest_meta(raw)[2:6]!=(1,0,0,490) or latest_meta(raw)[8:10]!=(0,0)):
        raise RuntimeError('Current A490 rollback/application/private bytes differ')
    return 490

if __name__=='__main__': trace.main(sys.modules[__name__])
