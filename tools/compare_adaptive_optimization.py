"""Offline, bit-exact before/after replay and host/ARM code comparison.

No serial/debugger/network imports; this tool never flashes or runs a board.
Host timing is not STM32 WCET. The frozen reference is the 2026-10-14 policy.
"""
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_foc_adaptive_optimized import compile_comparison, saved_inputs, FLAGS, OUT
from test_foc_adaptive_filter import prior

def run(args,**kwargs):
    return subprocess.run([str(a) for a in args],capture_output=True,text=True,
                          check=True,**kwargs).stdout

def main():
    exes=compile_comparison()
    result=dict(date='2026-10-15',hardware_access=False,flashed=False,
        delay_pairs=1,delay_us_at_20khz=50,policy_changed=False,saved=[],
        timing_note='Host averages are not Cortex-M4 worst-case IRQ timing.',
        benchmark_pairs_per_run=20000000,benchmark_runs_per_version=11)
    for path,samples in saved_inputs():
        text=''.join(f'{u} {v}\n' for u,v in samples)
        states={kind:run([exe,'--state'],input=text) for kind,exe in exes.items()}
        zero={kind:json.loads(run([exe,'--zero-window'],input=text)) for kind,exe in exes.items()}
        assert states['before']==states['after'] and zero['before']==zero['after']
        result['saved'].append(dict(source=str(path),
            input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),pairs=len(samples),
            output_centers=len(states['before'].splitlines()),all_states_equal=True,
            state_trace_sha256=hashlib.sha256(states['before'].encode()).hexdigest(),
            zero=zero['after']))
    times={kind:[] for kind in exes}; digests=set()
    for n in range(result['benchmark_runs_per_version']):
        # Interleave and alternate order; never run timing workloads in parallel.
        order=list(exes) if n%2==0 else list(reversed(exes))
        for kind in order:
            sample=json.loads(run([exes[kind],'--bench']))
            times[kind].append(sample['host_ns_per_pair']); digests.add(sample['digest'])
    assert len(digests)==1
    result['host_ns_per_pair']={kind:dict(median=statistics.median(v),runs=v) for kind,v in times.items()}
    result['benchmark_digest']=digests.pop()
    arm=prior.feedback.guard.ARM
    result['arm_probe']={}
    for kind,extra in [('before',['-DFOC_ADAPTIVE_REFERENCE=1']),('after',[])]:
        obj=OUT/f'optimized_arm_{kind}.o'
        run([arm/'arm-none-eabi-gcc.exe','-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-mcpu=cortex-m4','-mfloat-abi=hard','-mfpu=fpv4-sp-d16','-fstack-usage',
            '-I',ROOT/'firmware_common',*FLAGS,*extra,'-c',ROOT/'tests/foc_adaptive_arm_probe.c',
            '-o',obj])
        undefined=run([arm/'arm-none-eabi-nm.exe','-u',obj])
        asm=run([arm/'arm-none-eabi-objdump.exe','-d',obj])
        assert not undefined.strip()
        assert not re.search(r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s',asm)
        assert not re.search(r'\t(?:bl|blx)\s+',asm)
        sizes=run([arm/'arm-none-eabi-size.exe',obj]).splitlines()[-1].split()
        result['arm_probe'][kind]=dict(text_bytes=int(sizes[0]),
            stack_usage=obj.with_suffix('.su').read_text().strip(),
            no_undefined_symbols=True,no_fp=True,no_calls=True)
    result['builds']={}
    for slot in 'ab':
        folder=ROOT/f'foc2_app_{slot}/build/ProtectedAdaptiveFilter'
        binary=folder/'foc2.bin'
        su=folder/'CMakeFiles/foc2.dir/Core/Src/main.c.su'
        result['builds'][slot]=dict(bin_bytes=binary.stat().st_size,
            sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            adc_own_stack_frame=[line for line in su.read_text().splitlines()
                if 'ProtectedLoop_AdcIrq\t' in line])
    out=ROOT/'safety_backups/adaptive-filter-optimization-20261015'
    out.mkdir(exist_ok=True)
    path=out/'comparison.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved:',path)
    print('Saved traces and zero states equal:',len(result['saved']))
    print('Host timing only:',result['host_ns_per_pair'])
    print('ARM probe:',result['arm_probe'])
    print('Builds:',result['builds'])

if __name__=='__main__': main()
