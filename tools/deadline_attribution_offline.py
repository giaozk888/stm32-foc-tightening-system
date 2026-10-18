"""Build/host evidence only. No serial, debugger, flashing or boot selection.

Preserve historical pinned images and receipts in all earlier build folders.
"""
import json
from pathlib import Path
import re
import sys
import time
import pwm_pipeline_offline as prior

ROOT=prior.ROOT
OUT=ROOT/'tests/foc_adaptive_build/deadline_attribution_evidence'
MATRIX=prior.MATRIX+[(f'foc2_app_{s}','OneCyclePwmPipelineLight') for s in 'ab']

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    prior.OUT=OUT
    builds=[]
    for app,profile in MATRIX:
        name=app+'-'+profile
        directory=ROOT/app/'build/AttributionReview'/profile
        preset='OneCyclePwmPipeline' if profile.endswith('Light') else profile
        flags=['-DFOC_HEAVY_PROFILE_ENABLE=OFF'] if profile.endswith('Light') else []
        print('BUILD '+name,flush=True)
        prior.run(['cmake','--preset',preset,'-B',directory,*flags],ROOT/app,OUT/(name+'-configure.log'))
        log=prior.run(['cmake','--build',directory,'-j','8'],ROOT/app,OUT/(name+'-build.log'))
        elf=directory/'foc2.elf'; image=elf.with_suffix('.bin')
        builds.append(dict(app=app,profile=profile,build_dir=str(directory),
            bin_sha256=prior.digest(image) if image.exists() else None,
            elf_sha256=prior.digest(elf),memory=prior.memory_from_elf(directory,elf,name),
            warnings=sorted(set(re.findall(r'warning: (.*)',log)))))
    tests=[]
    for module in prior.TESTS+['test_foc_deadline_attribution']:
        print('TEST '+module,flush=True)
        log=prior.run([sys.executable,'-m','unittest','discover','-s','tests',
                       '-p',module+'.py','-v'],ROOT,OUT/(module+'.log'))
        count=re.search(r'Ran (\d+) tests?',log)
        if not count: raise RuntimeError('No test count '+module)
        tests.append(dict(module=module,passed=int(count[1])))
    receipt=dict(offline_only=True,hardware_access=False,boot_selection_changed=False,
        motor_started=False,created_unix=time.time(),builds=builds,tests=tests,
        test_count=sum(x['passed'] for x in tests))
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2),flush=True)

if __name__=='__main__': main()
