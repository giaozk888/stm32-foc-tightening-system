"""Pinned one-cycle hard-OFF board acceptance; offline by default.

One inactive-A stage, one ordinary bootloader trial, no START/forced confirm.
Reuse the existing whole-Flash/erase-page/fallback checks without relaxing them.
"""
import json
import sys
from pathlib import Path

import preempt_commit_board_test as base
import pwm_pipeline_report as report

ROOT,OUTPUT,PRIVATE=base.ROOT,base.OUTPUT,base.PRIVATE
IMAGE=ROOT/'foc2_app_a/build/OneCyclePwmPipeline/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='0a18156a94c3f3cc3c5a84e75840a9e1d8eb890ebb8ca03b860872490b5c7280'
ELF_SHA='c9f573a2b0b910f280708bf6b06cf32da14e08412400cc230bd60a087e4a6fcc'
SIZE=229236
PREFIX='pwm-pipeline-'
BASE_RECEIPT=OUTPUT/'preempt-commit-restore-1792207960510738800.json'
BASE_SHA='3dc5f909b0bade2d037c1766193ccf1a5c02b097c7edd3bf5d52a992dc7bd4a8'
BASE_META=(1112493908,3,2,0,0,598,228524,3332541027,210916,453748590,0,1622961613)
_verify,_decode=base.verify,base.decode

def image():
    data=IMAGE.read_bytes()
    receipt=json.loads((ROOT/'tests/foc_adaptive_build/pwm_pipeline_evidence/receipt.json').read_text())
    if (len(data)!=SIZE or base.tx.digest(data)!=SHA or
        base.tx.digest(ELF.read_bytes())!=ELF_SHA or base.prior.image_info(data)[0]!='A' or
        receipt.get('hardware_access') is not False or receipt.get('test_count')!=111 or
        not any(b.get('bin_sha256')==SHA and b.get('elf_sha256')==ELF_SHA
                for b in receipt['builds'])):
        raise ValueError('Exact offline-tested OneCyclePwmPipeline A BIN/ELF/receipt required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1',b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4',b'PWM COMMIT',b'HYPOTHETICAL PWM',
                   b'actual_late_commit_count',b'SERVICE_WALL_INCLUDING_CHILDREN'):
        if marker not in data: raise ValueError('Missing hard-off/pipeline identity')
    return data

def configure():
    # Process-local, pinned identities only; no device access or metadata edit.
    values={k:globals()[k] for k in ('IMAGE','ELF','SHA','ELF_SHA','SIZE','PREFIX',
                                   'BASE_RECEIPT','BASE_SHA','BASE_META')}
    for module in (base,base.confirm,base.confirm.base,base.old,base.prior,base.tx):
        for k,v in values.items(): setattr(module,k,v)
        module.image=image
    base.report=report
    base.verify=verify
    base.decode=decode
    base.configure=configure

def verify():
    _verify()
    symbols=report.base.schema.symbols(ELF)
    for name in ('cl_pwm_pending','ProtectedLoop_PwmEntry','foc_pending_generated',
                 'foc_pending_held','foc_pending_empty','foc_pending_commit_max_cycles',
                 'foc_pending_generation_max_cycles','foc_tim7_preempt_max_cycles'):
        if name not in symbols: raise ValueError('Missing pipeline symbol: '+name)
    if 'PowerStage_Enable' in symbols or 'FocAdcTiming_HardOffCommitProbe' in symbols:
        raise ValueError('Power enable or intrusive probe in hard-OFF image')

def acceptance_failure(p):
    a,t,n=p['actual_ccr'],p['timing'],p['pipeline']
    if not p['priorities']['ok'] or p['priorities']['unexpected']:
        return 'Priority inventory invalid'
    if not t['frames'] or t['deadline_miss']:
        return 'No FOC frames or wall deadline miss'
    if not a['actual_ccr_writes'] or not a['points'] or not n['generated']:
        return 'No valid actual pipeline publication'
    if (a['actual_late_count'] or a['latch_crossings'] or a['late_update_count'] or
        a['invalid'] or a['blocked'] or a['post_unsafe'] or
        a['possible_mixed_latch_count'] or a['pwm_update_margin_ticks_min']<=170):
        return 'Actual commit late/invalid/blocked or inside existing guard'
    if n['tim7_preempt_max_cycles']:
        return 'TIM7 unexpectedly attributed as ADC preempt'
    return None

def decode(row,data):
    _decode(row,data)
    p=row.get('preempt_commit')
    if not p:
        if row.get('hardware_attempted') and row.get('mode')=='trial':
            row.update(pass_=False,pipeline_evidence_missing=True)
        return
    reason=acceptance_failure(p)
    row['pipeline_acceptance_failure']=reason
    row['pipeline_digital_timing_pass']=bool(row['pass_'] and reason is None)
    row['motor_closed_loop_verified']=False
    row['physical_shadow_latch_directly_observed']=False
    if row['pass_'] and reason: row.update(pass_=False,failure=reason)

def main():
    configure()
    if len(sys.argv)==1:
        image(); verify()
        print('OFFLINE PASS: pinned OneCyclePwmPipeline A, confirmed B fallback; no devices')
        return 0
    return base.main()

if __name__=='__main__': raise SystemExit(main())
