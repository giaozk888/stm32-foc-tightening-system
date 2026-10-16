"""Offline actual-C equivalence and linked compact IRQ proofs; no board I/O."""
import hashlib
import json
import re
import subprocess
import unittest
import test_foc_ram_hot_path as ram

ROOT=ram.ROOT
GCC=ram.adaptive.GCC
OUT=ROOT/'tests/foc_adaptive_build'
FLAGS=ram.FLAGS+['-DFOC_IRQ_COMPACT=1']
COMMON=ROOT/'firmware_common'
ARM=ram.ARM
run=ram.command

def host(name,sources,flags=FLAGS,includes=(),opt='-O2'):
    OUT.mkdir(exist_ok=True)
    exe=OUT/(name+'.exe')
    run(GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
        '-I',COMMON,*[x for p in includes for x in ('-I',p)],*flags,*sources,'-o',exe)
    return run(exe)

class CompactTests(unittest.TestCase):
    def test_generic_and_fixed_encoder_operations_identical(self):
        for opt in ('-Os','-O2'):
            generic=host('compact_engine_reference_'+opt,
                [ROOT/'tests/as5047p_host/dma_engine_test.c',COMMON/'as5047p_dma_engine.c'],
                [],[ROOT/'foc2_app_b/Core/Inc'],opt)
            fixed=host('compact_engine_fixed_'+opt,
                [ROOT/'tests/as5047p_host/dma_engine_compact_test.c'],
                [],[ROOT/'foc2_app_b/Core/Inc'],opt)
            self.assertEqual(generic,fixed)
            self.assertIn('0 failures',fixed)
            print(fixed.strip())

    def test_actual_guardian_decisions_identical(self):
        sources=[ROOT/'tests/foc_compact_guard_host.c',COMMON/'foc_current_zero.c',
                 COMMON/'foc_zero_median.c',COMMON/'foc_zero_robust.c']
        for opt in ('-Os','-O2'):
            self.assertEqual(host('compact_guard_ref_'+opt,sources,ram.FLAGS,opt=opt),
                             host('compact_guard_new_'+opt,sources,opt=opt))

    def test_adc_ack_and_live_clock_checks_retained(self):
        self.assertIn('PASS',host('compact_adc_irq',
            [ROOT/'tests/protected_adc_irq_host.c',COMMON/'foc_current_zero.c',
             COMMON/'foc_zero_median.c',COMMON/'foc_zero_robust.c']))
        for flags,name in ((ram.FLAGS,'reference'),(FLAGS,'compact')):
            text=host('compact_adc_adapter_'+name,[ROOT/'tests/foc_adc_adapter_host.c',
                COMMON/'foc_adc_timing_stm32.c',COMMON/'foc_adc_raw_buffer.c',
                COMMON/'foc_adc_window.c'],flags+['-DFOC_ADC_SENSE_TOPOLOGY=2'],
                [ROOT/'tests/foc_adc_mock'])
            self.assertIn('PASS',text)

    def test_background_two_block_budget_and_scan_cadence(self):
        self.assertIn('PASS',host('compact_worker',[ROOT/'tests/foc_adc_statistics_task_host.c',
            COMMON/'foc_adc_statistics_task.c'],includes=[ROOT/'tests/foc_adc_mock']))

    def test_adaptive_filter_and_protection_equivalence(self):
        self.assertEqual(host('compact_filter_ref',[ROOT/'tests/foc_adaptive_equivalence.c'],ram.FLAGS),
                         host('compact_filter_new',[ROOT/'tests/foc_adaptive_equivalence.c']))

    def test_opt_in_only_and_old_images_not_overwritten(self):
        for slot,sha in [('a','02edbca738e617aece13bf2a2fdbdd1ab69ca9a39ec699ca41fc29239e3cd9bf'),
                         ('b','0db686fbd249496c646900afae7b5b3a285b8754d3ed997b8f78ef5d3a472878')]:
            base=ROOT/f'foc2_app_{slot}'
            preset=next(p for p in json.loads((base/'CMakePresets.json').read_text('utf-8'))
                        ['configurePresets'] if p['name']=='ProtectedIrqCompact')
            self.assertEqual(preset['inherits'],'ProtectedAdaptiveRam')
            self.assertEqual(preset['cacheVariables'],{'FOC_IRQ_COMPACT':'ON'})
            self.assertEqual(hashlib.sha256((base/'build/ProtectedAdaptiveRam/foc2.bin').read_bytes()).hexdigest(),sha)
        bad=subprocess.run([GCC,'-std=c11','-fsyntax-only','-I',str(COMMON),
            *[f for f in FLAGS if f!='-DFOC_RAM_HOT_PATH=1'],
            str(ROOT/'tests/foc_guard_integer_host.c')],capture_output=True)
        self.assertNotEqual(bad.returncode,0)

    def test_linked_sram_and_no_encoder_indirect_ops(self):
        for slot in 'ab':
            folder=ROOT/f'foc2_app_{slot}/build/ProtectedIrqCompact'
            symbols=run(ARM/'arm-none-eabi-nm.exe','-S',folder/'foc2.elf')
            table={m[3]:int(m[0],16) for line in symbols.splitlines() if len(m:=line.split())==4}
            for name in ('ProtectedLoop_AdcIrq','TIM7_DAC_IRQHandler','TIM2_IRQHandler',
                         'DMA1_Channel4_IRQHandler','AsDma_Guard','AsDma_Begin'):
                self.assertTrue(0x20000000<=table[name]<0x20008000,(slot,name))
            asm=run(ARM/'arm-none-eabi-objdump.exe','-d',folder/'foc2.elf')
            blocks={m[1]:m[2] for m in re.finditer(
                r'^[0-9a-f]+ <([^>]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)',asm,re.M|re.S)}
            pending=['AsDma_Guard','AsDma_Begin','AsDma_RxComplete']; seen=set()
            while pending:
                name=pending.pop()
                if name in seen: continue
                seen.add(name); body=blocks[name]
                # No function-pointer dispatch in fixed ops on the hot normal path.
                # FaultSnapshot/Finish legitimately call the registered fault hook.
                if name not in ('Complete','Finish','FaultSnapshot'):
                    self.assertNotRegex(body,r'\t(?:blx|bx)\s+r[0-9]+\b',name)
                for target in re.findall(r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>',body):
                    if target in blocks and not target.endswith('_veneer'): pending.append(target)
            # Guardian stays integer-only all the way through fault closure.
            pending=['TIM7_DAC_IRQHandler']; seen=set()
            while pending:
                name=pending.pop()
                if name in seen: continue
                seen.add(name); body=blocks[name]
                self.assertFalse(name.endswith('_veneer'),name)
                self.assertNotRegex(body,r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s',name)
                self.assertNotRegex(body,r'\t(?:blx|bx)\s+r[0-9]+\b',name)
                self.assertNotRegex(body,r'<(?:memcpy|__aeabi_|HAL_Delay|malloc)')
                pending.extend(re.findall(r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>',body))
            mapping=(folder/'foc2.map').read_text('utf-8')
            end=re.search(r'^\._user_heap_stack\s*\n\s*0x([a-f0-9]+)\s+0x([a-f0-9]+)',mapping,re.M)
            used=sum(int(x,16) for x in end.groups())-0x20000000
            self.assertGreaterEqual(0x1ffc0-used,8*1024)
            self.assertLessEqual((folder/'foc2.bin').stat().st_size,224*1024)

if __name__=='__main__': unittest.main()
