"""Exact repaired hard-off A reacceptance from the restored locked B.

Stage requires drive 12 V OFF; commit separately requires normally powered
current-sense inputs with motor leads disconnected. Neither phase permits
motion, clearing faults, forced confirmation or automatic reset retries.
"""
import hashlib
import struct

import median_control_acceptance as core
from zero_async_clock_acceptance import locked_baseline
from zero_median_contrast import PINNED

SHA='4ba450ebf3af17f32f418be57639ebfc6981268627066d5375f0d36d23f41bf1'
IMAGE=core.ROOT/'foc2_app_a/build/MedianControlComputeOnly20261012/foc2.bin'
OUTPUT=core.ROOT/'safety_backups/median-control-warmstart-20261012'
BASELINE_GENERATION=414
FAILED_SHA=core.SHA


def image():
    data=IMAGE.read_bytes()
    if core.image_info(data)[0]!='A' or hashlib.sha256(data).hexdigest()!=SHA:
        raise RuntimeError('Exact repaired compute-only A required')
    reset=struct.unpack_from('<I',data,4)[0]&~1
    if data[reset-0x08008000:reset-0x08008000+2]!=b'\x72\xb6':
        raise RuntimeError('Actual Reset_Handler must begin with CPSID i')
    for marker in (b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0',b'SD=MOE=CCER=0'):
        if marker not in data: raise RuntimeError('Missing hard-off compute marker')
    return data


def baseline(data):
    result=locked_baseline(data,known={'A':frozenset((FAILED_SHA,)),
                                     'B':frozenset((PINNED['B'],))})
    if result['current']!='B' or result['generation']!=BASELINE_GENERATION:
        raise RuntimeError('Only restored original locked B generation 414 admitted')
    return result


def main():
    # Reuse the reviewed stage/one-FW-END/cleanup protocol, with explicit
    # repaired-image and restored-baseline pins. The historical pins remain
    # intact in the original module for auditing the failed first trial.
    core.SHA=SHA
    core.IMAGE=IMAGE
    core.OUTPUT=OUTPUT
    core.BASELINE_GENERATION=BASELINE_GENERATION
    core.image=image
    core.baseline=baseline
    core.main()


if __name__=='__main__': main()
