"""Pinned heavy attribution A acceptance; offline by default, no motor START.

Reuse unchanged full-Flash, inactive-page, hard-off and normal-boot checks.
Never reinterpret a historic image's SRAM as the new deadline schema.
"""
import json
import sys
import pwm_pipeline_board_test as pipeline
import deadline_attribution_report as report

base=pipeline.base
ROOT,OUTPUT,PRIVATE=pipeline.ROOT,pipeline.OUTPUT,pipeline.PRIVATE
IMAGE=ROOT/'foc2_app_a/build/AttributionReview/OneCyclePwmPipeline/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='ce8cacaf9e106d0c80c980cbcd63a0410110dab32fb59c4e4bac0a51a7008a70'
ELF_SHA='d6e0bf8143591a6d11fbf88566aa64ff59e78a8e724c1d8eea43a45e66c8bd21'
SIZE=229348
PREFIX='deadline-attribution-'
BASE_RECEIPT=OUTPUT/'pwm-pipeline-restore-1792211380702854900.json'
BASE_SHA='c345a2cefcc598f26caafe70c7a156dfef9db46c273d5b72d0c25d51dbdb70f0'
BASE_META=(1112493908,3,2,0,0,601,229236,4212128574,210916,453748590,0,3303513161)


def image():
    data=IMAGE.read_bytes()
    receipt=json.loads((ROOT/'tests/foc_adaptive_build/deadline_attribution_evidence/receipt.json').read_text())
    if (len(data)!=SIZE or base.tx.digest(data)!=SHA or
        base.tx.digest(ELF.read_bytes())!=ELF_SHA or base.prior.image_info(data)[0]!='A' or
        receipt.get('hardware_access') is not False or receipt.get('test_count')!=117 or
        not any(b.get('app')=='foc2_app_a' and b.get('profile')=='OneCyclePwmPipeline'
                and b.get('bin_sha256')==SHA and b.get('elf_sha256')==ELF_SHA
                for b in receipt['builds'])):
        raise ValueError('Exact offline-tested heavy attribution A BIN/ELF/receipt required')
    for marker in (b'NAME=FAST_CURRENT_REJECT HARD_OFF=1',b'METHOD=TWO_SAMPLE',
                   b'FILTER=NONE OC=RAW_CONFIRM_4',b'PWM COMMIT',b'HYPOTHETICAL PWM',
                   b'DEADLINE',b'actual_late_commit_count',b'SERVICE_WALL_INCLUDING_CHILDREN'):
        if marker not in data: raise ValueError('Missing hard-off/attribution identity')
    return data


def configure():
    values={k:globals()[k] for k in ('IMAGE','ELF','SHA','ELF_SHA','SIZE','PREFIX',
                                   'BASE_RECEIPT','BASE_SHA','BASE_META')}
    for module in (pipeline,base,base.confirm,base.confirm.base,base.old,base.prior,base.tx):
        for key,value in values.items(): setattr(module,key,value)
        module.image=image
    base.report=report
    base.verify=verify
    base.decode=decode
    base.configure=configure


def verify():
    pipeline.verify()
    symbols=report.pipeline.base.schema.symbols(ELF)
    address,size=symbols['deadline_snapshot']
    if size!=64 or not 0x20000000<=address<=0x20020000-size:
        raise ValueError('Wrong new deadline snapshot layout')
    if 'foc_stamp_assisted_count' not in symbols:
        raise ValueError('Heavy assisted attribution required')


def attribution_failure(p):
    snap=p['deadline_snapshot']
    if p['timing']['deadline_miss']:
        if snap['status']!='VALID_FIRST_MISS':
            return 'First deadline attribution not trustworthy'
    elif snap['status']!='NO_SNAPSHOT':
        return 'Unexpected deadline snapshot without a miss'
    return None


def decode(row,data):
    pipeline.decode(row,data)
    p=row.get('preempt_commit')
    if not p: return
    reason=attribution_failure(p)
    row['deadline_attribution_failure']=reason
    row['first_deadline_attribution_valid']=p['deadline_snapshot']['status']=='VALID_FIRST_MISS'
    if reason: row.update(pass_=False,failure=reason)


def main():
    configure()
    if len(sys.argv)==1:
        image(); verify()
        print('OFFLINE PASS: pinned heavy attribution A / B601 fallback / no devices')
        return 0
    return base.main()


if __name__=='__main__': raise SystemExit(main())
