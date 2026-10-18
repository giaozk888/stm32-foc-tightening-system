"""Offline only: production IRQ hooks and real-preload probe under mocks."""
import hashlib
import json
import re
import subprocess
import unittest
import test_foc_fast_current_reject as fast
import test_foc_rc_protected_candidate as rc

ROOT=fast.ROOT
FLAGS=fast.FLAGS+['-DFOC_FAST_REJECT_COMPUTE_ONLY=1','-DFOC_PREEMPT_COMMIT_PROBE=1']

class PreemptCommitProbeTests(unittest.TestCase):
    def test_production_attribution_hooks(self):
        fast.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('preempt_attribution'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock','-I',fast.COMMON,*FLAGS,
                fast.COMMON/'foc_preempt_probe_stm32.c',ROOT/'tests/foc_preempt_attribution_host.c','-o',exe)
            self.assertIn('PASS production exclusive IRQ attribution',fast.run(exe))

    def test_real_preload_adapter(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('preempt_commit'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock','-I',fast.COMMON,
                *rc.ADAPTER_FLAGS,*FLAGS,'-DFOC_ONE_CYCLE_PWM_PIPELINE=1',fast.COMMON/'foc_adc_window.c',
                fast.COMMON/'foc_adc_raw_buffer.c',fast.COMMON/'foc_adc_timing_stm32.c',
                ROOT/'tests/foc_pwm_pipeline_commit_host.c','-o',exe)
            self.assertIn('PASS pipeline actual CCR',fast.run(exe))

    def test_hard_off_compile_guards(self):
        for extra in ([],['-DFOC_FAST_CURRENT_REJECT=1'],FLAGS+['-DFOC_FAST_PATH_PROFILE=1'],
                      FLAGS+['-DFOC_IRQ_SOURCE_TRACE=1']):
            p=subprocess.run([fast.legacy.GCC,'-std=c11','-fsyntax-only','-x','c',
                '-I',str(fast.COMMON),'-DFOC_PREEMPT_COMMIT_PROBE=1',*extra,'-'],
                input='#include "foc_preempt_probe.h"\n',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)

    def test_new_irq_hooks_never_mask_or_change_priorities(self):
        src=(fast.COMMON/'foc_preempt_probe_stm32.c').read_text('utf-8')
        self.assertNotRegex(src,r'\b(?:__disable_irq|__set_PRIMASK|__set_BASEPRI|NVIC_SetPriority|HAL_NVIC_SetPriority)\s*\(')
        hot=src.split('void FocPreempt_CheckPriorities')[0]
        self.assertNotRegex(hot,r'\b(?:printf|snprintf|UART_\w+|malloc|free|for|while)\s*\(')
        probe=(fast.COMMON/'foc_adc_timing_stm32.c').read_text('utf-8').split('int FocAdcTiming_PipelineCommit')[1].split('#endif')[0]
        self.assertNotRegex(probe,r'->(?:CCER|BDTR|EGR|CCR4)\s*[|&]?=')
        self.assertNotRegex(probe,r'->(?:CR1|SR)\s*[|&]?=')

    def test_image_separate_and_slot_bounded(self):
        for slot in 'ab':
            build=ROOT/f'foc2_app_{slot}/build/PreemptCommitProbe'
            self.assertLessEqual((build/'foc2.bin').stat().st_size,224*1024)
            commands=json.loads((build/'compile_commands.json').read_text('utf-8'))
            cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
            self.assertIn('-DFOC_PREEMPT_COMMIT_PROBE=1',cmd)
            self.assertIn('-DFOC_FAST_REJECT_COMPUTE_ONLY=1',cmd)
            self.assertNotIn('-DFOC_FAST_PATH_PROFILE=1',cmd)
            self.assertNotIn('-ffast-math',cmd)
            symbols=fast.run(fast.ARM/'arm-none-eabi-nm.exe','-S',build/'foc2.elf')
            for name in ('foc_preempt_irq','foc_preempt_timing','foc_pwm_write_profile',
                         'foc_pwm_duty_profile'):
                self.assertIn(name,symbols)
            self.assertNotIn(' PowerStage_Enable\n',symbols)

    def test_no_new_compiler_warnings(self):
        for slot in 'ab':
            app=ROOT/f'foc2_app_{slot}'
            groups={name:json.loads((app/'build'/name/'compile_commands.json').read_text('utf-8'))
                for name in ('PreemptCommitProbe','FastCurrentRejectComputeOnly')}
            for suffix in ('/Core/Src/main.c','/Core/Src/stm32g4xx_it.c',
                           '/foc_adc_timing_stm32.c','/as5047p_dma_stm32.c'):
                warnings={}
                for preset,commands in groups.items():
                    cmd=next(x['command'] for x in commands if x['file'].endswith(suffix))
                    cmd=re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd)
                    p=subprocess.run(cmd,cwd=app/'build'/preset,capture_output=True,text=True)
                    self.assertEqual(p.returncode,0,p.stderr)
                    warnings[preset]=set(re.findall(r'warning: (.*)',p.stderr))
                self.assertFalse(warnings['PreemptCommitProbe']-warnings['FastCurrentRejectComputeOnly'])
            cmd=next(x['command'] for x in groups['PreemptCommitProbe']
                if x['file'].endswith('/foc_preempt_probe_stm32.c'))
            cmd=re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd)
            p=subprocess.run(cmd,cwd=app/'build/PreemptCommitProbe',capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertNotIn('warning:',p.stderr)

if __name__=='__main__': unittest.main()
