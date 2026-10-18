"""Offline build/regression receipt. No serial, debugger or boot operations."""
import json
import re
import sys
import time
import deadline_attribution_offline as previous
prior=previous.prior
ROOT=prior.ROOT
OUT=ROOT/'tests/foc_adaptive_build/encoder_foc_first_evidence'
MATRIX=previous.MATRIX+[(f'foc2_app_{s}',p) for s in 'ab'
                     for p in ('EncoderFocFirst','EncoderFocFirstLight')]

def main():
    OUT.mkdir(parents=True,exist_ok=True); prior.OUT=OUT
    builds=[]
    for app,profile in MATRIX:
        name=app+'-'+profile; build=ROOT/app/'build/EncoderReview'/profile
        preset=profile.removesuffix('Light')
        flags=['-DFOC_HEAVY_PROFILE_ENABLE=OFF'] if profile.endswith('Light') else []
        print('BUILD '+name,flush=True)
        prior.run(['cmake','--preset',preset,'-B',build,*flags],ROOT/app,OUT/(name+'-configure.log'))
        log=prior.run(['cmake','--build',build,'-j','8'],ROOT/app,OUT/(name+'-build.log'))
        elf=build/'foc2.elf'; image=elf.with_suffix('.bin')
        builds.append(dict(app=app,profile=profile,build_dir=str(build),
            bin_sha256=prior.digest(image) if image.exists() else None,
            elf_sha256=prior.digest(elf),memory=prior.memory_from_elf(build,elf,name),
            warnings=sorted(set(re.findall(r'warning: (.*)',log)))))
    tests=[]
    for module in prior.TESTS+['test_foc_deadline_attribution','test_encoder_foc_first',
                               'test_deadline_attribution_board_test']:
        print('TEST '+module,flush=True)
        log=prior.run([sys.executable,'-m','unittest','discover','-s','tests','-p',module+'.py','-v'],
                      ROOT,OUT/(module+'.log'))
        tests.append(dict(module=module,passed=int(re.search(r'Ran (\d+) tests?',log)[1])))
    receipt=dict(offline_only=True,hardware_access=False,boot_selection_changed=False,
        motor_started=False,created_unix=time.time(),builds=builds,tests=tests,
        test_count=sum(t['passed'] for t in tests))
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2),flush=True)

if __name__=='__main__': main()
