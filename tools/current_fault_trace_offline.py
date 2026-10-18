"""Current-confirmation RAM trace builds/tests only; no hardware imports/commands.

Keep pinned images intact. Record capacity failures explicitly, never enlarge a
slot, change control compilation flags or present an unlinked image as usable.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tests/current_invalid_rolling_trace_build'
TESTS=('test_current_fault_trace','test_foc_cur_confirm_cycles',
    'test_foc_fast_current_reject','test_foc_timeout_diagnostics',
    'test_foc_pwm_pipeline','test_pipeline_closed_loop',
    'test_pipeline_closed_loop_board_test','test_pipeline_closed_loop_trial')


def run(command,cwd,log):
    p=subprocess.run([str(x) for x in command],cwd=cwd,capture_output=True,text=True)
    text=p.stdout+p.stderr
    (OUT/log).write_text(text,encoding='utf-8')
    return p.returncode,text


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def memory(elf,trace):
    p=subprocess.run(['D:/software/arm/bin/arm-none-eabi-size.exe','-A',str(elf)],
        capture_output=True,text=True,check=True)
    rows=[(int(m[1]),int(m[2])) for m in re.finditer(r'^\.\S+\s+(\d+)\s+(\d+)$',p.stdout,re.M)]
    end=max(addr+size for size,addr in rows if 0x20000000<=addr<0x20020000)
    ring=0
    if trace:
        nm=subprocess.run(['D:/software/arm/bin/arm-none-eabi-nm.exe','-S',str(elf)],
            capture_output=True,text=True,check=True).stdout
        ring=int(re.search(r'^\w+\s+(\w+)\s+\w\s+foc_current_fault_trace$',nm,re.M)[1],16)
    return dict(ram_linked=end-0x20000000,ram_region=0x1ffc0,
        ram_ring=ring,ram_cursor=4 if trace else 0,
        frame_bytes=(72 if ring==1172 else 52) if trace else 0,frames=16 if trace else 0)


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rolling',action='store_true',default=True,
        help='CTR2 separate folders (default); pinned CTR1 artifacts are never overwritten')
    parser.add_argument('--expanded-tests',action='store_true',
        help='Also run the existing integrated control/profiling regression suites')
    args=parser.parse_args()
    folders=('RollingTraceBaseline','CurrentInvalidRollingTrace')
    OUT.mkdir(exist_ok=True)
    receipt=dict(hardware_access=False,motor_started=False,boot_selection_changed=False,
        control_policy_changed=False,builds=[],tests=[],mcu_timing='NOT_REMEASURED')
    for slot in 'ab':
        app=ROOT/f'foc2_app_{slot}'
        for profile in ('ProtectedPipelineClosedLoop','CurrentFaultTrace'):
            name=f'{slot}-{profile}'
            directory=app/'build'/folders[profile=='CurrentFaultTrace']
            print('BUILD '+name,flush=True)
            rc,text=run(['cmake','--preset',profile,'-B',directory],app,name+'-configure.log')
            if rc: raise RuntimeError(text)
            rc,text=run(['cmake','--build',directory,'-j','8'],app,name+'-build.log')
            row=dict(slot=slot,profile=profile,build_dir=str(directory),linked=not rc,
                warnings=sorted(set(re.findall(r'warning: (.*)',text))))
            if rc:
                overflow=re.search(r"region `FLASH' overflowed by (\d+) bytes",text)
                if not overflow: raise RuntimeError(text)
                row['flash_overflow_bytes']=int(overflow[1])
                row['usable_image']=False
                print('CAPACITY BLOCKED '+name+' '+overflow[1]+' bytes',flush=True)
            else:
                image=directory/'foc2.bin'
                row.update(image_bytes=image.stat().st_size,bin_sha256=digest(image),
                    elf_sha256=digest(directory/'foc2.elf'),
                    memory=memory(directory/'foc2.elf',profile=='CurrentFaultTrace'))
                row['flash_region_bytes']=224*1024
                row['flash_free_bytes']=224*1024-row['image_bytes']
                row['ram_free_bytes']=row['memory']['ram_region']-row['memory']['ram_linked']
                entries=json.loads((directory/'compile_commands.json').read_text('utf-8'))
                main_command=next(e['command'] for e in entries if e['file'].endswith('/Core/Src/main.c'))
                enabled=profile=='CurrentFaultTrace'
                if f'-DFOC_CURRENT_FAULT_TRACE_ENABLE={int(enabled)} ' not in main_command:
                    raise RuntimeError('Wrong diagnostic switch')
                nm=subprocess.run(['D:/software/arm/bin/arm-none-eabi-nm.exe',
                    str(directory/'foc2.elf')],capture_output=True,text=True,check=True).stdout
                if (' foc_current_fault_trace' in nm)!=enabled:
                    raise RuntimeError('Trace symbol does not match switch')
                row['trace_symbols_present']=enabled
                if enabled:
                    trace_command=next(e['command'] for e in entries if e['file'].endswith('/foc_current_fault_trace.c'))
                    for flag in ('-ffunction-sections','-fdata-sections','-Os'):
                        if flag not in trace_command: raise RuntimeError('Missing '+flag)
                    if '--gc-sections' not in (directory/'build.ninja').read_text('utf-8'):
                        raise RuntimeError('Missing section GC')
                    row['section_gc_and_trace_Os_verified']=True
                if profile=='ProtectedPipelineClosedLoop':
                    pinned=app/'build/ClosedLoopIntegration/ProtectedPipelineClosedLoop/foc2.bin'
                    row['pinned_bin_identical']=digest(image)==digest(pinned)
                    if not row['pinned_bin_identical']: raise RuntimeError('Trace-OFF baseline changed')
            receipt['builds'].append(row)
        # Compile only the touched TU/new recorder to compare inherited source
        # warnings even when an incremental build emits no warnings at all.
        groups={}
        for profile,folder in zip(('baseline','trace'),folders):
            directory=app/'build'/folder
            entries=json.loads((directory/'compile_commands.json').read_text('utf-8'))
            warnings=set()
            for entry in entries:
                if entry['file'].endswith(('/Core/Src/main.c','/foc_current_fault_trace.c')):
                    command=re.sub(r' -o \S+ -c ',' -fsyntax-only ',entry['command'])
                    p=subprocess.run(command,cwd=directory,capture_output=True,text=True)
                    if p.returncode: raise RuntimeError(p.stderr)
                    warnings.update(re.findall(r'warning: (.*)',p.stderr))
            groups[profile]=warnings
        receipt['builds'][-1]['new_source_warnings']=sorted(groups['trace']-groups['baseline'])
        receipt['builds'][-1]['inherited_source_warnings']=sorted(groups['baseline'])
        base,trace=receipt['builds'][-2:]
        trace['new_build_warnings']=sorted(set(trace['warnings'])-set(base['warnings']))
        if trace['new_build_warnings']: raise RuntimeError('New build warning')
        if trace['linked']:
            trace['ram_delta_bytes']=trace['memory']['ram_linked']-base['memory']['ram_linked']
            trace['flash_delta_bytes']=trace['image_bytes']-base['image_bytes']
        if groups['trace']-groups['baseline']: raise RuntimeError('New source warning')
    modules=list(TESTS)
    if args.expanded_tests:
        import os
        import pipeline_closed_loop_offline as pipeline
        os.environ['FOC_ENCODER_REVIEW_DIR']='ClosedLoopIntegration'
        modules=list(dict.fromkeys(pipeline.prior.TESTS+[
            'test_foc_deadline_attribution','test_encoder_foc_first',
            'test_deadline_attribution_board_test','test_encoder_foc_first_board_test',
            'test_health_confirmation_wait','test_encoder_health_board_test',
            'test_pipeline_closed_loop','test_latest_original_fsm',*modules,
            'test_current_fault_trace_board_test','test_two_sample_state_audit']))
    for module in modules:
        print('TEST '+module,flush=True)
        rc,text=run([sys.executable,'-m','unittest','discover','-s','tests','-p',module+'.py','-v'],
            ROOT,module+'.log')
        ran=re.search(r'Ran (\d+) tests?',text)
        count=int(ran[1]) if ran else 0
        failures=len(re.findall(r'^FAIL:',text,re.M))
        errors=len(re.findall(r'^ERROR:',text,re.M))
        receipt['tests'].append(dict(module=module,ran=count,passed=count-failures-errors,
            failures=failures,errors=errors,success=rc==0,return_code=rc))
        if rc: print('TEST FAILED '+module+' (see log)',flush=True)
    receipt['test_count']=sum(r['ran'] for r in receipt['tests'])
    receipt['passed_count']=sum(r['passed'] for r in receipt['tests'])
    receipt['all_tests_passed']=all(r['success'] for r in receipt['tests'])
    receipt['all_images_linked']=all(r['linked'] for r in receipt['builds'])
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2),flush=True)
    return 0 if receipt['all_images_linked'] and receipt['all_tests_passed'] else 2


if __name__=='__main__':
    raise SystemExit(main())
