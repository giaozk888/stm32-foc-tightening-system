"""Offline equivalence and linked SRAM/startup proofs; never opens the board."""
import hashlib
import json
import re
import subprocess
import unittest
import test_foc_adaptive_filter as adaptive

ROOT=adaptive.ROOT
ARM=adaptive.prior.feedback.guard.ARM
FLAGS=adaptive.prior.GATE+['-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1',
    '-DFOC_ZERO_TOTAL_BUDGET_OFF=1','-DFOC_RAM_HOT_PATH=1']

def command(*args):
    return subprocess.run([str(x) for x in args],check=True,capture_output=True,text=True).stdout

class RamHotPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        adaptive.OUT.mkdir(exist_ok=True)
        adaptive.prior.feedback.guard.pair.binding.ProtectedLoopTests.setUpClass()

    def test_adaptive_state_and_feedback_decisions_identical(self):
        for opt in ('-Os','-O2'):
            results=[]
            for ram in (False,True):
                exe=adaptive.OUT/f'ram_equivalence_{opt}_{ram}.exe'
                flags=FLAGS if ram else FLAGS[:-1]
                command(adaptive.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                    '-UNDEBUG','-I',ROOT/'firmware_common',*flags,
                    ROOT/'tests/foc_adaptive_equivalence.c','-o',exe)
                results.append(command(exe))
            self.assertEqual(*results)

    def test_actual_locked_binding_and_adc_ack_order(self):
        binding=adaptive.prior.feedback.guard.pair.binding
        for source in ('foc_adaptive_binding_host.c','protected_adc_irq_host.c'):
            exe=adaptive.OUT/('ram_'+source+'.exe')
            command(adaptive.GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',ROOT/'firmware_common',*FLAGS,ROOT/'tests'/source,
                ROOT/'firmware_common/foc_zero_median.c',ROOT/'firmware_common/foc_zero_robust.c',
                ROOT/'firmware_common/foc_current_zero.c','-o',exe)
            self.assertIn('PASS',command(exe))

    def test_opt_in_only_and_ieee_checks_remain(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            cfg=next(p for p in presets['configurePresets'] if p['name']=='ProtectedAdaptiveRam')
            self.assertEqual(cfg['inherits'],'ProtectedAdaptiveNoZeroQuota')
            self.assertEqual(cfg['cacheVariables'],{'FOC_RAM_HOT_PATH':'ON'})
        for drop in ('-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1','-DFOC_GATE_REUSE=1'):
            result=subprocess.run([adaptive.GCC,'-std=c11','-fsyntax-only','-I',str(ROOT/'firmware_common'),
                *[f for f in FLAGS if f!=drop],str(ROOT/'tests/foc_guard_integer_host.c')],capture_output=True)
            self.assertNotEqual(result.returncode,0)

    def test_linked_interrupt_callers_and_kernels_really_in_initialized_ram(self):
        required=('ADC1_2_IRQHandler','ProtectedLoop_AdcIrq',
            'TIM7_DAC_IRQHandler','ProtectedLoop_GuardIrqBody','ProtectedLoop_HealthCaptured',
            'FocFeedbackGuard_OutputOff','FocFeedbackGuard_Disarm',
            'FocAdcTiming_FastCanStart',
            'FocAdcTiming_RecordRaw','FocRawBuffer_Push','FocFast_SinCos',
            'DMA1_Channel4_IRQHandler','DMA1_Channel5_IRQHandler','TIM2_IRQHandler',
            'EncoderDma_TimerIrqBody','EncoderDma_RxIrqBody','AsDma_Guard','AsDma_Begin',
            'AsDma_RxComplete','FocIrqLoad_Enter','FocIrqLoad_Leave','FocIrqLoad_Read')
        for slot in 'ab':
            folder=ROOT/f'foc2_app_{slot}/build/ProtectedAdaptiveRam'
            symbols=command(ARM/'arm-none-eabi-nm.exe','-S',folder/'foc2.elf')
            table={m[3]:int(m[0],16) for line in symbols.splitlines()
                   if len(m:=line.split())==4}
            self.assertGreater(table['_edata'] if '_edata' in table else 0x20003000,0x20000000)
            for name in required:
                self.assertTrue(name in table,(slot,name))
                self.assertTrue(0x20000000<=table[name]<0x20008000,(slot,name,hex(table[name])))
            mapping=(folder/'foc2.map').read_text('utf-8')
            data=re.search(r'^\.data\s+0x([a-f0-9]+)\s+0x([a-f0-9]+) load address 0x([a-f0-9]+)',mapping,re.M)
            self.assertIsNotNone(data)
            start,size,load=map(lambda v:int(v,16),data.groups())
            self.assertTrue(all(start<=table[n]<start+size for n in required))
            # O2 fully inlines pair, math and WorkEnd into the RAM ADC owner.
            for optional in ('FOC_CurrentLoopStep','ProtectedLoop_Pair','ProtectedLoop_WorkEnd'):
                if optional in table:
                    self.assertTrue(start<=table[optional]<start+size)
            self.assertLess(size,12*1024)
            # .data's flash image must actually exist in the slot binary.
            raw=(folder/'foc2.bin').read_bytes()
            base=0x08008000 if slot=='a' else 0x08040000
            self.assertGreaterEqual(len(raw),load-base+size)
            self.assertLessEqual(len(raw),224*1024)
            end=re.search(r'^\._user_heap_stack\s*\n\s*0x([a-f0-9]+)\s+0x([a-f0-9]+)',mapping,re.M)
            self.assertIsNotNone(end)
            used=sum(int(x,16) for x in end.groups())-0x20000000
            self.assertGreaterEqual(0x1ffc0-used,8*1024)
            startup=(ROOT/f'foc2_app_{slot}/startup_stm32g474xx.s').read_text('utf-8')
            self.assertLess(startup.index('CopyDataInit:'),startup.index('cpsie i'))
            linker=(ROOT/f'foc2_app_{slot}/STM32G474XX_FLASH.ld').read_text('utf-8')
            self.assertIn('*(.RamFunc*)',linker)

    def test_ram_guardian_still_integer_only_no_hidden_blocking_helpers(self):
        for slot in 'ab':
            elf=ROOT/f'foc2_app_{slot}/build/ProtectedAdaptiveRam/foc2.elf'
            asm=command(ARM/'arm-none-eabi-objdump.exe','-d',elf)
            blocks={m.group(1):m.group(2) for m in re.finditer(
                r'^[0-9a-f]+ <([^>]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)',asm,re.M|re.S)}
            pending=['TIM7_DAC_IRQHandler']; seen=set()
            while pending:
                name=pending.pop()
                if name in seen: continue
                seen.add(name); self.assertIn(name,blocks); body=blocks[name]
                # A Flash veneer uses ldr pc rather than bl: reject it here so
                # the graph proof cannot silently stop at a linker trampoline.
                self.assertNotRegex(name,r'_veneer$')
                self.assertNotRegex(body,r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s')
                self.assertNotRegex(body,r'\t(?:blx|bx)\s+r[0-9]+\b')
                self.assertNotRegex(body,r'<(?:memcpy|__aeabi_|HAL_Delay|malloc)')
                pending.extend(re.findall(r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>',body))

    def test_original_noquota_images_remain_immutable(self):
        for slot,sha in [('a','2d6a4cbff35764cbe2dbef87fee60a375b0c132530b9187a00bcc486532eb462'),
                         ('b','cea42a3732029abf9b8f0ccd3691cb8d266ef5459242ca2ffd496fe997236f06')]:
            self.assertEqual(hashlib.sha256((ROOT/f'foc2_app_{slot}/build/ProtectedAdaptiveNoZeroQuota/foc2.bin').read_bytes()).hexdigest(),sha)

if __name__=='__main__': unittest.main()
