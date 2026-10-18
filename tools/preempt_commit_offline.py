"""Build/regression evidence only. No serial, debugger, flash or boot selection."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tests/foc_adaptive_build/preempt_commit_evidence'
MATRIX=[('foc2','Debug')]+[(f'foc2_app_{slot}',preset) for slot in 'ab'
    for preset in ('FastCurrentReject','FastCurrentRejectComputeOnly','FastPathTiming','PreemptCommitProbe')]
TESTS=['test_foc_fast_current_reject','test_foc_cur_confirm_cycles',
    'test_foc_timeout_diagnostics','test_filtered_protection_candidate',
    'test_current_protection_layers','test_overcurrent_confirm','test_protected_closed_loop',
    'test_foc_adc_spread','test_foc_adc_rc_policy','test_foc_adc_ram_bench',
    'test_foc_adc_integration','test_foc_adc_clock','test_foc_rc_protected_candidate',
    'test_foc_pwm_boundary','test_foc_pwm_boundary_lite','test_foc_path_profile',
    'test_fast_path_profile_board_test','test_foc_preempt_commit_probe']

def run(args,cwd,log):
    proc=subprocess.run(args,cwd=cwd,text=True,stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,timeout=600)
    log.write_text(proc.stdout,encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(f'{args}: exit={proc.returncode}\n{proc.stdout[-6000:]}')
    return proc.stdout

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for app,preset in MATRIX:
        key=f'{app}-{preset}'
        print('BUILD '+key,flush=True)
        run(['cmake','--preset',preset],ROOT/app,OUT/(key+'-configure.log'))
        log=run(['cmake','--build','--preset',preset,'-j','8'],ROOT/app,OUT/(key+'-build.log'))
        image=ROOT/app/'build'/preset/'foc2.bin'
        elf=image.with_suffix('.elf')
        has_bin=image.exists()
        if not has_bin: image=elf # Main Debug has no BIN post-build rule.
        rows.append(dict(app=app,preset=preset,image_kind='bin' if has_bin else 'elf',
            image_bytes=image.stat().st_size,
            bin_sha256=hashlib.sha256(image.read_bytes()).hexdigest() if has_bin else None,
            elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
            warnings=sorted(set(re.findall(r'warning: (.*)',log)))))
    tests=[]
    for name in TESTS:
        print('TEST '+name,flush=True)
        log=run([sys.executable,'-m','unittest','discover','-s','tests','-p',name+'.py','-v'],
                ROOT,OUT/(name+'.log'))
        count=re.search(r'Ran (\d+) tests?',log)
        if not count: raise RuntimeError('Missing unittest result '+name)
        tests.append(dict(module=name,passed=int(count[1])))
    receipt=dict(offline_only=True,hardware_access=False,boot_selection_changed=False,
        motor_started=False,created_unix=time.time(),builds=rows,tests=tests,
        test_count=sum(row['passed'] for row in tests))
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2),flush=True)

if __name__=='__main__': main()
