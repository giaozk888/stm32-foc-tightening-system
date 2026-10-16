"""Pinned A453 -> B repair-budget 6/4 HARD-OFF test profile only.

stage: physical drive OFF, official UART Transfer, no commit/reset.
commit: powered sensing, motor disconnected, one normal trial, no motion.
Preserve the rejected 3/2 image, historical tools/evidence and A fallback.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib
import feedback_safety_stage as stage_tool
import feedback_safety_commit as commit_tool
from zero_retest_deploy import latest_meta

IMAGE=stage_tool.ROOT/'foc2_app_b/build/FeedbackBudget2x20261013/foc2.bin'
SHA='89f6e449c105bb4eb8ea4d5e52fecea8dc7443061abb1f175758a637e2a6de00'
OUTPUT=stage_tool.ROOT/'safety_backups/feedback-budget2x-live-20261013'
GEN=453
REPAIR_BUDGET=(6,4)
REFERENCE=stage_tool.OUTPUT/'rollback-audit-1791888347973040200.json'
# Shared commit engine validates the complete UART staging status before END.
require_staged=stage_tool.require_staged

def image():
    data=IMAGE.read_bytes()
    if (len(data)!=207088 or stage_tool.image_info(data)[0]!='B' or
            hashlib.sha256(data).hexdigest()!=SHA):
        raise RuntimeError('Exact offline-tested doubled-budget B required')
    for marker in (b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0',b'SD=MOE=CCER=0',
                   b'RAW=VALIDITY_ONLY FILTERED=2_OF_3',b'GUARD_US=25',
                   b'SCOPE=PAIR_CHECK_TO_FOC_END',b'TIMEOUT_TEST_REJECTED',
                   b'REPAIR_MAX=%u STREAK_MAX=%u'):
        if marker not in data: raise RuntimeError('Missing hard-off/budget marker')
    if b'OPEN_LOAD_ONLY' in data: raise RuntimeError('Bridge fixture forbidden')
    pc=(struct.unpack_from('<I',data,4)[0]&~1)-0x08040000
    if data[pc:pc+2]!=b'\x72\xb6': raise RuntimeError('Reset IRQ mask missing')
    return data

def baseline_identity(raw):
    if len(raw)!=0x80000: raise RuntimeError('Complete private baseline required')
    meta=latest_meta(raw)
    if meta[2:6]!=(1,0,0,GEN) or meta[8:10]!=(0,0):
        raise RuntimeError('Only confirmed A453 with normally rejected B admitted')
    a=raw[0x8000:0x8000+meta[6]]
    old_b=(stage_tool.ROOT/'foc2_app_b/build/FeedbackSafety20261013/foc2.bin').read_bytes()
    if (hashlib.sha256(a).hexdigest()!=stage_tool.OLD_A or zlib.crc32(a)!=meta[7] or
            hashlib.sha256(old_b).hexdigest()!=stage_tool.SHA or
            raw[0x40000:0x40000+len(old_b)]!=old_b):
        raise RuntimeError('A fallback or rejected B identity differs')
    return dict(current='A',generation=GEN,rejected_b_preserved=True)

def baseline(raw):
    row=baseline_identity(raw)
    evidence=json.loads(REFERENCE.read_text('utf-8'))
    if (evidence.get('pass_') is not True or evidence.get('read_only_closeout') is not True or
            evidence.get('prior_trial_pass') is not False or
            evidence.get('fw',{}).get('GEN')!=str(GEN) or
            evidence.get('image_sha256')!=stage_tool.SHA):
        raise RuntimeError('Exact independently verified rollback evidence required')
    path=Path(evidence['rollback_backup']).resolve()
    if path.parent!=(stage_tool.OUTPUT/'private').resolve():
        raise RuntimeError('Rollback baseline must stay private')
    if raw!=path.read_bytes(): raise RuntimeError('Flash changed since verified A453 rollback')
    return row

def main():
    if len(sys.argv)<2 or sys.argv[1] not in ('stage','commit'):
        raise SystemExit('Choose stage or commit; neither can start a motor')
    mode=sys.argv.pop(1)
    profile=sys.modules[__name__]
    if mode=='stage': stage_tool.main(profile)
    else: commit_tool.main(profile)

if __name__=='__main__': main()
