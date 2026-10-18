"""Build/regression integration only. No serial/debugger/device/boot imports."""
import json
import os
import re
import sys
import time
import encoder_foc_first_offline as history

prior=history.prior
ROOT=prior.ROOT
OUT=ROOT/'tests/foc_adaptive_build/pipeline_closed_loop_evidence'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    prior.OUT=OUT
    builds=[]
    matrix=history.MATRIX+[(f'foc2_app_{s}','ProtectedPipelineClosedLoop') for s in 'ab']
    for app,profile in matrix:
        name=app+'-'+profile
        build=ROOT/app/'build/ClosedLoopIntegration'/profile
        preset=profile.removesuffix('Light')
        flags=['-DFOC_HEAVY_PROFILE_ENABLE=OFF'] if profile.endswith('Light') else []
        print('BUILD '+name,flush=True)
        prior.run(['cmake','--preset',preset,'-B',build,*flags],ROOT/app,OUT/(name+'-configure.log'))
        log=prior.run(['cmake','--build',build,'-j','8'],ROOT/app,OUT/(name+'-build.log'))
        elf=build/'foc2.elf'; image=elf.with_suffix('.bin')
        memory=prior.memory_from_elf(build,elf,name)
        if image.exists() and image.stat().st_size>224*1024:
            raise RuntimeError('Slot overflow '+name)
        builds.append(dict(app=app,profile=profile,build_dir=str(build),
            image_bytes=image.stat().st_size if image.exists() else None,
            bin_sha256=prior.digest(image) if image.exists() else None,
            elf_sha256=prior.digest(elf),memory=memory,
            warnings=sorted(set(re.findall(r'warning: (.*)',log)))))
    old=json.loads((ROOT/'tests/foc_adaptive_build/encoder_health_evidence/receipt.json').read_text('utf-8'))
    compared=0
    for row in old['builds']:
        new=next(r for r in builds if (r['app'],r['profile'])==(row['app'],row['profile']))
        if row['bin_sha256']:
            if new['bin_sha256']!=row['bin_sha256']:
                raise RuntimeError('Historic profile binary changed '+row['app']+' '+row['profile'])
            compared+=1
    tests=[]
    os.environ['FOC_ENCODER_REVIEW_DIR']='ClosedLoopIntegration'
    modules=prior.TESTS+['test_foc_deadline_attribution','test_encoder_foc_first',
        'test_deadline_attribution_board_test','test_encoder_foc_first_board_test',
        'test_health_confirmation_wait','test_encoder_health_board_test',
        'test_pipeline_closed_loop','test_latest_original_fsm']
    for module in modules:
        print('TEST '+module,flush=True)
        log=prior.run([sys.executable,'-m','unittest','discover','-s','tests','-p',module+'.py','-v'],
                      ROOT,OUT/(module+'.log'))
        tests.append(dict(module=module,passed=int(re.search(r'Ran (\d+) tests?',log)[1])))
    receipt=dict(offline_only=True,hardware_access=False,boot_selection_changed=False,
        motor_started=False,created_unix=time.time(),builds=builds,tests=tests,
        test_count=sum(r['passed'] for r in tests),historical_bin_unchanged_count=compared)
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: {len(builds)} builds, {receipt["test_count"]} tests, {compared} unchanged old BINs',flush=True)

if __name__=='__main__': main()
