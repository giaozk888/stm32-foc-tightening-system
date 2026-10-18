"""Offline only: adversarial IRQ interleavings in the production reader."""
import re
import struct
import sys
import unittest
import json
import subprocess
from unittest.mock import patch
import test_foc_pwm_pipeline as pipeline
import test_foc_rc_protected_candidate as rc

fast=pipeline.fast
ROOT=fast.ROOT

class DeadlineAttributionTests(unittest.TestCase):
    def test_current_heavy_light_builds_and_warning_delta(self):
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build/AttributionReview'
            groups={}
            for profile in ('FastCurrentRejectComputeOnly','OneCyclePwmPipeline',
                            'OneCyclePwmPipelineLight'):
                build=root/profile
                self.assertLessEqual((build/'foc2.bin').stat().st_size,224*1024)
                groups[profile]=json.loads((build/'compile_commands.json').read_text('utf-8'))
            for profile,heavy in (('OneCyclePwmPipeline',1),('OneCyclePwmPipelineLight',0)):
                build=root/profile
                symbols=fast.run(fast.ARM/'arm-none-eabi-nm.exe','-S',build/'foc2.elf')
                self.assertIn(' ProtectedLoop_PwmEntry',symbols)
                self.assertNotIn(' PowerStage_Enable\n',symbols)
                self.assertEqual(' deadline_snapshot\n' in symbols,bool(heavy))
                for suffix in ('/Core/Src/main.c','/Core/Src/stm32g4xx_it.c',
                               '/as5047p_dma_stm32.c','/foc_adc_timing_stm32.c'):
                    warnings={}
                    for candidate in ('FastCurrentRejectComputeOnly',profile):
                        command=next(x['command'] for x in groups[candidate]
                                     if x['file'].endswith(suffix))
                        if candidate==profile:
                            self.assertIn(f'-DFOC_HEAVY_PROFILE_ENABLE={heavy}',command)
                        p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',command),
                            cwd=root/candidate,capture_output=True,text=True)
                        self.assertEqual(p.returncode,0,p.stderr)
                        warnings[candidate]=set(re.findall(r'warning: (.*)',p.stderr))
                    self.assertFalse(warnings[profile]-warnings['FastCurrentRejectComputeOnly'],warnings)
                command=next(x['command'] for x in groups[profile]
                             if x['file'].endswith('/foc_preempt_probe_stm32.c'))
                p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',command),
                    cwd=build,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertNotIn('warning:',p.stderr)

    def test_new_ram_schema_rejects_false_validity(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import deadline_attribution_report as report
        ram=bytearray(128)
        def decode(words):
            struct.pack_into('<16I',ram,0,*words)
            with patch.object(report.pipeline,'decode',return_value={}), \
                 patch.object(report.pipeline.base.schema,'symbols',
                              return_value={'deadline_snapshot':(0x20000000,64)}):
                return report.decode(None,ram,None,None)['deadline_snapshot']
        words=[1,1,9000,7000,1200,4,600,2,200,1,2000,1234,1,100,9100,20]
        self.assertEqual(decode(words)['status'],'VALID_FIRST_MISS')
        for index in (0,2,3,4,6,8,10,13,14):
            bad=words.copy(); bad[index]+=1
            if index==0: bad[index]=0
            with self.subTest(index=index), self.assertRaises(ValueError): decode(bad)
        words[1]=0
        self.assertEqual(decode(words)['status'],'CAPTURED_BUT_UNTRUSTED')

    def test_light_actual_commit_safety_matches_heavy(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/f'deadline_light_commit_{opt}.exe'
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-pedantic','-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock',
                '-I',fast.COMMON,*rc.ADAPTER_FLAGS,*pipeline.FLAGS,
                '-DFOC_HEAVY_PROFILE_ENABLE=0',fast.COMMON/'foc_adc_window.c',
                fast.COMMON/'foc_adc_raw_buffer.c',fast.COMMON/'foc_adc_timing_stm32.c',
                ROOT/'tests/foc_pwm_pipeline_commit_host.c','-o',exe)
            for case in range(15):
                self.assertIn('PASS pipeline actual CCR',fast.run(exe,case))

    def test_assisted_deadline_and_light_profile(self):
        fast.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            for heavy in (0,1):
                exe=fast.OUT/f'deadline_attribution_{opt}_{heavy}.exe'
                fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                    '-pedantic','-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock',
                    '-I',fast.COMMON,*pipeline.FLAGS,'-DFOC_PRE_CAPTURE_TEST=1',
                    f'-DFOC_HEAVY_PROFILE_ENABLE={heavy}',
                    fast.COMMON/'foc_preempt_probe_stm32.c',
                    ROOT/'tests/foc_deadline_attribution_host.c','-o',exe)
                self.assertIn('PASS coherent first deadline',fast.run(exe))

    def test_encoder_priority_and_no_rtos_or_heavy_math_in_irq(self):
        src=(fast.COMMON/'as5047p_dma_stm32.c').read_text('utf-8')
        self.assertIn('#define AS_DMA_IRQ_PRIORITY 1U',src)
        self.assertNotRegex(src,r'\b(?:[xv]\w+FromISR|portYIELD_FROM_ISR|printf|UART_\w+)\s*\(')
        engine=(fast.COMMON/'as5047p_dma_engine.c').read_text('utf-8')
        self.assertNotRegex(engine,r'\b(?:float|double|atan2f|sinf|cosf|printf)\b')
        irq=src.split('FOC_RAM_PATH void DMA1_Channel4_IRQHandler(void)',1)[1]
        self.assertNotIn('ParityIsOdd',irq)
        # Parity remains a bounded protocol operation needed before publication,
        # not an angle/speed filter transplanted into the acquisition ISR.
        self.assertIn('AS5047P_ParityIsOdd',engine)
        for slot in 'ab':
            cfg=(ROOT/f'foc2_app_{slot}/Core/Inc/FreeRTOSConfig.h').read_text('utf-8')
            self.assertRegex(cfg,r'configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY\s+5')

    def test_probe_no_mask_no_retry_no_uart_in_hot_path(self):
        src=(fast.COMMON/'foc_preempt_probe_stm32.c').read_text('utf-8')
        hot=src.split('void FocPreempt_CheckPriorities')[0]
        self.assertNotRegex(hot,r'\b(?:for|while|__disable_irq|__set_PRIMASK|__set_BASEPRI|UART_\w+)\s*\(')
        self.assertLess(hot.index('deadline_snapshot.timer_span='),
                        hot.index('deadline_snapshot.valid=f->valid'))
        self.assertLess(hot.index('deadline_snapshot.captured=1U'),
                        hot.index('deadline_snapshot.valid=f->valid'))

if __name__=='__main__': unittest.main()
