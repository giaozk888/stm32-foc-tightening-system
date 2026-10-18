"""Build and host regressions ONLY. Never import a device/boot runner.

Historical evidence build directories are preserved: reviewed old profiles
are rebuilt into build/PipelineReview/<preset>, not over pinned old ELFs.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tests/foc_adaptive_build/pwm_pipeline_evidence'
MATRIX=[('foc2','Debug')]+[(f'foc2_app_{s}',p) for s in 'ab' for p in
    ('FastCurrentReject','FastCurrentRejectComputeOnly','FastPathTiming',
     'PreemptCommitProbe','OneCyclePwmPipeline')]
TESTS=[
    'test_foc_fast_current_reject','test_foc_cur_confirm_cycles',
    'test_foc_timeout_diagnostics','test_filtered_protection_candidate',
    'test_current_protection_layers','test_overcurrent_confirm','test_protected_closed_loop',
    'test_foc_adc_spread','test_foc_adc_rc_policy','test_foc_adc_ram_bench',
    'test_foc_adc_integration','test_foc_adc_clock','test_foc_rc_protected_candidate',
    'test_foc_pwm_boundary','test_foc_pwm_boundary_lite','test_foc_path_profile',
    'test_fast_path_profile_board_test','test_foc_preempt_commit_probe','test_foc_pwm_pipeline']

def run(args,cwd,log):
    p=subprocess.run([str(a) for a in args],cwd=cwd,text=True,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=600)
    log.write_text(p.stdout,encoding='utf-8')
    if p.returncode: raise RuntimeError(f'{args}: exit={p.returncode}\n{p.stdout[-6500:]}')
    return p.stdout

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def memory_from_elf(directory,elf,key):
    """Record linked extents even when Ninja does not relink this run."""
    cache=(directory/'CMakeCache.txt').read_text(encoding='utf-8')
    objdump=re.search(r'^CMAKE_OBJDUMP:FILEPATH=(.+)$',cache,re.M)
    if not objdump: raise RuntimeError('Missing configured objdump')
    listing=run([objdump[1].strip(),'-h',elf],directory,OUT/(key+'-sections.log'))
    ram_end=0x20000000; flash=[]
    for m in re.finditer(r'^\s*\d+\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+'
                         r'([0-9a-f]+)[^\r\n]*\r?\n([^\r\n]+)',listing,re.M):
        size,vma,lma=(int(m[i],16) for i in (1,2,3))
        if not size or 'ALLOC' not in m[4]: continue
        if 0x20000000<=vma<0x20020000: ram_end=max(ram_end,vma+size)
        if 'LOAD' in m[4] and 0x08000000<=lma<0x08080000: flash.append((lma,lma+size))
    if not flash: raise RuntimeError('Missing loadable flash sections')
    return dict(RAM=ram_end-0x20000000,FLASH=max(b for _,b in flash)-min(a for a,_ in flash))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for app,preset in MATRIX:
        key=app+'-'+preset
        directory=ROOT/app/'build'
        directory=directory/preset if preset=='OneCyclePwmPipeline' else directory/'PipelineReview'/preset
        print('BUILD '+key,flush=True)
        run(['cmake','--preset',preset,'-B',directory],ROOT/app,OUT/(key+'-configure.log'))
        output=run(['cmake','--build',directory,'-j','8'],ROOT/app,OUT/(key+'-build.log'))
        elf=directory/'foc2.elf'; image=elf.with_suffix('.bin')
        memory=memory_from_elf(directory,elf,key)
        rows.append(dict(app=app,preset=preset,build_dir=str(directory),
            image_bytes=image.stat().st_size if image.exists() else None,
            bin_sha256=digest(image) if image.exists() else None,elf_sha256=digest(elf),
            memory_bytes=memory,
            warnings=sorted(set(re.findall(r'warning: (.*)',output)))))
    tests=[]
    for name in TESTS:
        print('TEST '+name,flush=True)
        output=run([sys.executable,'-m','unittest','discover','-s','tests','-p',name+'.py','-v'],
            ROOT,OUT/(name+'.log'))
        count=re.search(r'Ran (\d+) tests?',output)
        if not count: raise RuntimeError('Missing unittest result '+name)
        tests.append(dict(module=name,passed=int(count[1])))
    receipt=dict(offline_only=True,hardware_access=False,boot_selection_changed=False,
        motor_started=False,created_unix=time.time(),builds=rows,tests=tests,
        test_count=sum(t['passed'] for t in tests))
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2),flush=True)

if __name__=='__main__': main()
