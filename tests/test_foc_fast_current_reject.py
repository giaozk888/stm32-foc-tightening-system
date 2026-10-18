"""Offline only: no serial, debugger, flash or motor commands."""
import json
import subprocess
import unittest
from pathlib import Path
import test_latest_original_fsm as legacy

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/'firmware_common'
OUT=ROOT/'tests/foc_adaptive_build'
ARM=Path('D:/software/arm/bin')
FLAGS=legacy.FLAGS+['-DFOC_FAST_CURRENT_REJECT=1']

def run(*args):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=60)
    if p.returncode: raise AssertionError(p.stdout+p.stderr)
    return p.stdout

class FastCurrentRejectTests(unittest.TestCase):
    def test_core_and_actual_irq_at_os_o2(self):
        OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            for name in ('foc_fast_current_reject_host','foc_fast_reject_irq_host'):
                exe=OUT/(name+opt+'.exe')
                run(legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                    '-I',COMMON,*FLAGS,ROOT/'tests'/f'{name}.c','-o',exe)
                self.assertIn('PASS',run(exe))

    def test_no_mixed_research_mode(self):
        for flag in ('FOC_ENABLE_LEGACY_CURRENT_REPAIR','FOC_RC_DEFERRED_SHADOW','FOC_REPAIR_WINDOW_TRACE'):
            p=subprocess.run([legacy.GCC,'-std=c11','-fsyntax-only','-I',str(COMMON),
                *FLAGS,'-D'+flag+'=1',str(ROOT/'tests/foc_fast_current_reject_host.c')],capture_output=True)
            self.assertNotEqual(p.returncode,0)

    def test_invalid_threshold_configuration_rejected(self):
        for setting in ('FOC_CURRENT_JUMP_THRESHOLD_COUNTS=0',
                'FOC_CURRENT_RETURN_TOL_COUNTS=61','FOC_CURRENT_CONFIRM_TOL_COUNTS=61',
                'FOC_CURRENT_UNRESOLVED_LIMIT=0','FOC_CURRENT_UNRESOLVED_LIMIT=256'):
            p=subprocess.run([legacy.GCC,'-std=c11','-fsyntax-only','-I',str(COMMON),
                *FLAGS,'-D'+setting,str(ROOT/'tests/foc_current_impulse_kernel.c')],capture_output=True)
            self.assertNotEqual(p.returncode,0,setting)

    def test_arm_discriminator_is_integer_only_constant_work(self):
        import re
        OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            obj=OUT/('impulse_kernel'+opt+'.o')
            run(ARM/'arm-none-eabi-gcc.exe','-std=c11',opt,'-mcpu=cortex-m4','-mthumb',
                '-mfpu=fpv4-sp-d16','-mfloat-abi=hard','-Wall','-Wextra','-Werror','-pedantic',
                '-I',COMMON,*FLAGS,'-c',ROOT/'tests/foc_current_impulse_kernel.c','-o',obj)
            asm=run(ARM/'arm-none-eabi-objdump.exe','-d',obj)
            # No call-outs (including abs/division helpers), VFP, allocation,
            # IO or sort. The source has no loops or input-sized storage.
            self.assertNotRegex(asm,r'\b(?:bl|blx|v[a-z]+|[us]div)\s')
            core=(COMMON/'foc_current_fast_reject.h').read_text('utf-8')
            code=re.sub(r'/\*.*?\*/','',core,flags=re.S)
            self.assertNotRegex(code,r'\b(?:for|while|malloc|printf|sqrt|sort)\s*\(')

    def test_host_replay_adapter_rebases_observed_endpoints(self):
        OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=OUT/('impulse_replay'+opt+'.exe')
            run(legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-I',COMMON,*FLAGS,ROOT/'tests/foc_current_impulse_replay_host.c','-o',exe)
            p=subprocess.run([str(exe)],input='1626 1609\n1560 1557\n1561 1558\n1562 1559\n',
                text=True,capture_output=True,check=True)
            row=json.loads(p.stdout)
            self.assertEqual((row['samples'],row['held'],row['accepted'],row['transition'],row['fault']),
                (3,1,2,1,0))

    def test_actual_shutdown_binding_and_compute_only_admission(self):
        OUT.mkdir(exist_ok=True)
        for mode in ([],['-DFOC_FAST_REJECT_COMPUTE_ONLY=1']):
            exe=OUT/('fast_binding'+str(bool(mode))+'.exe')
            run(legacy.GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',COMMON,*FLAGS,*mode,ROOT/'tests/foc_fast_reject_binding_host.c',
                COMMON/'foc_current_zero.c',COMMON/'foc_zero_median.c',
                COMMON/'foc_zero_robust.c','-o',exe)
            self.assertIn('PASS',run(exe))

    def test_linked_profiles_and_release_flags(self):
        for slot in 'ab':
            for preset in ('FastCurrentReject','FastCurrentRejectComputeOnly'):
                build=ROOT/f'foc2_app_{slot}/build/{preset}'
                data=(build/'foc2.bin').read_bytes()
                self.assertLessEqual(len(data),224*1024)
                self.assertIn(b'OC=RAW_CONFIRM_4',data)
                self.assertIn(b'CURRENT VALIDATION samples=',data)
                self.assertIn(b'METHOD=TWO_SAMPLE',data)
                self.assertIn(b'unresolved_max_cycles=',data)
                symbols=run(ARM/'arm-none-eabi-nm.exe',build/'foc2.elf')
                self.assertNotIn('FocTrend4_',symbols)
                self.assertNotIn('FocRcDeferredPlan_',symbols)
                asm=run(ARM/'arm-none-eabi-objdump.exe','-d','--disassemble=ProtectedLoop_AdcIrq',build/'foc2.elf')
                for forbidden in ('<FocCurrentMedian_Push','<FocAdaptive_','<malloc','<printf','<UART_'):
                    self.assertNotIn(forbidden,asm)
                commands=json.loads((build/'compile_commands.json').read_text('utf-8'))
                for item in commands:
                    if item['file'].endswith(('main.c','stm32g4xx_it.c')):
                        self.assertIn('-O2',item['command'])
                        self.assertNotIn('-Ofast',item['command'])
                        self.assertNotIn('-ffast-math',item['command'])

    def test_no_new_main_compile_warnings(self):
        # Compare one source under otherwise identical profiles. The project
        # already has unused-function warnings; do not hide them globally.
        import re
        for slot in 'ab':
            build=ROOT/f'foc2_app_{slot}/build/FastCurrentReject'
            commands=json.loads((build/'compile_commands.json').read_text('utf-8'))
            cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
            def warnings(command):
                command=re.sub(r' -o \S+ -c ', ' -fsyntax-only ',command)
                p=subprocess.run(command,cwd=build,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                return set(re.findall(r'warning: (.*)',p.stderr))
            current=warnings(cmd)
            baseline=warnings(cmd.replace('-DFOC_FAST_CURRENT_REJECT=1 ', '').replace(
                '-DFOC_ENABLE_LEGACY_CURRENT_REPAIR=0','-DFOC_ENABLE_LEGACY_CURRENT_REPAIR=1'))
            self.assertFalse(current-baseline,current-baseline)

if __name__=='__main__': unittest.main()
