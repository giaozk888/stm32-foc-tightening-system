"""Offline only: never opens serial/debugger or writes a device."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
import test_foc_rc_protected_candidate as rc

ROOT=rc.ROOT
FLAGS=rc.ADAPTER_FLAGS+['-DFOC_PWM_BOUNDARY_TRACE=1']

class PwmBoundaryTests(unittest.TestCase):
    def test_pure_boundary_arithmetic(self):
        rc.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=rc.OUT/('pwm_boundary_pure'+opt+'.exe')
            rc.run(rc.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',rc.COMMON,ROOT/'tests/foc_pwm_boundary_host.c','-o',exe)
            self.assertIn('PASS boundary arithmetic',rc.run(exe))

    def test_real_adapters(self):
        rc.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=rc.OUT/('pwm_boundary'+opt+'.exe')
            rc.run(rc.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',rc.COMMON,'-I',ROOT/'tests/foc_adc_mock',*FLAGS,
                rc.COMMON/'foc_adc_window.c',rc.COMMON/'foc_adc_raw_buffer.c',
                rc.COMMON/'foc_adc_timing_stm32.c',rc.COMMON/'foc_irq_load_stm32.c',
                ROOT/'tests/foc_pwm_boundary_adapter_host.c','-o',exe)
            self.assertIn('PASS real boundary adapters',rc.run(exe))

    def test_single_owner_and_complete_profile_required(self):
        for extra in (['-DFOC_IRQ_SOURCE_TRACE=1'], ['-UFOC_ADC_RC_PROTECTED_CANDIDATE'],
                      ['-UFOC_FEEDBACK_FAST_PATH'], ['-UFOC_STARTUP_TRACE']):
            p=subprocess.run([rc.GCC,'-std=c11','-fsyntax-only','-x','c','-I',str(rc.COMMON),
                *FLAGS,*extra,'-'],input='#include "foc_hot_path.h"\n',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)

    def test_linked_new_profile_and_prior_images_unchanged(self):
        pins={'a':'0990cdf2ec7fde9c169afdc3d67cb2d3ea772ae29fd90b0c9b4f565565f05e20',
              'b':'9fd54166df782cce3e737ecfebe67bc4aff8f15a005fca1f1136c91bb8786f44'}
        for slot in 'ab':
            app=ROOT/f'foc2_app_{slot}'
            presets=json.loads((app/'CMakePresets.json').read_text('utf-8'))
            p=next(p for p in presets['configurePresets'] if p['name']=='RcBoundaryAttribution')
            self.assertEqual(p['inherits'],'RcSamplingOptimizedCandidate')
            self.assertEqual(hashlib.sha256((app/'build/RcSamplingOptimizedCandidate/foc2.bin').read_bytes()).hexdigest(),pins[slot])
            build=app/'build/RcBoundaryAttribution'
            image=(build/'foc2.bin').read_bytes()
            for marker in (b'NAME=RC_BOUNDARY_TRACE HARD_OFF=0 ADMISSION=0',
                           b'ADC BOUNDARY FRAME',b'ADC BOUNDARY IRQ',b'HW_VERIFIED=0',
                           b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000'):
                self.assertIn(marker,image)
            self.assertLessEqual(len(image),224*1024)
            asm=rc.run(Path(r'D:\software\arm\bin\arm-none-eabi-objdump.exe'),'-d',build/'foc2.elf')
            ready=asm.split('<FocAdcTiming_RcActuationReady>:',1)[1].split('\n\n',1)[0]
            self.assertRegex(ready,r'movs\s+r0, #0')
            commit=asm.split('<FocAdcTiming_CommitBeforeBottom>:',1)[1].split('\n\n',1)[0]
            self.assertRegex(commit,r'movs\s+r0, #0')
            for name in ('DMA1_Channel4_IRQHandler','DMA1_Channel5_IRQHandler',
                         'TIM2_IRQHandler','TIM7_DAC_IRQHandler'):
                body=asm.split('<'+name+'>:',1)[1].split('\n\n',1)[0]
                self.assertIn('FocIrqSource_Enter',body,name)
                self.assertIn('FocIrqSource_Leave',body,name)
            inner=asm.split('<ProtectedLoop_AdcIrq>:',1)[1].split('\n\n',1)[0]
            self.assertNotIn('FocIrqSource_FrameBegin',inner)
            self.assertNotIn('FocIrqSource_FrameEnd',inner)
            symbols=rc.run(Path(r'D:\software\arm\bin\arm-none-eabi-nm.exe'),'-S','-n',build/'foc2.elf')
            for name in ('FocIrqSource_Enter','FocIrqSource_Leave','FocIrqSource_FrameBegin','FocIrqSource_FrameEnd'):
                m=re.search(r'^([0-9a-f]+) [0-9a-f]+ [Tt] '+name+r'$',symbols,re.M)
                self.assertIsNotNone(m,name)
                self.assertTrue(0x20000000<=int(m[1],16)<0x20010000,name)

if __name__=='__main__': unittest.main()
