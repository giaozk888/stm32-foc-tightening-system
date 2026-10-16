import hashlib
import json
import re
import subprocess
import unittest
import test_foc_feedback_fast as feedback

ROOT=feedback.ROOT
GATE=feedback.FLAGS+['-DFOC_GATE_REUSE=1']
TRACE=GATE+['-DFOC_IRQ_SOURCE_TRACE=1']


class IrqSourceTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): feedback.guard.pair.binding.ProtectedLoopTests.setUpClass()

    def compile_host(self,source,name,flags=TRACE,opt='-O2'):
        out=feedback.guard.pair.binding.OUT.with_name(name+'.exe')
        subprocess.run([feedback.guard.pair.binding.GCC,'-std=c11',opt,'-Wall','-Wextra',
            '-Werror','-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),
            *flags,str(ROOT/source),'-o',str(out)],check=True)
        return out

    def test_exclusive_nesting_million_events_and_wrap(self):
        for opt in ('-Os','-O2'):
            out=self.compile_host('tests/foc_irq_sources_host.c','irq_sources_'+opt,opt=opt)
            subprocess.run([str(out)],check=True)

    def test_actual_binding_stop_break_and_first_late_freeze(self):
        for flags,name,count in ((GATE,'gate_reuse',44),(TRACE,'irq_trace',45)):
            out=feedback.guard.pair.binding.OUT.with_name(name+'.exe')
            subprocess.run(feedback.guard.pair.binding.ProtectedLoopTests.base+flags+['-o',str(out)],check=True)
            for case in range(count):
                result=subprocess.run([str(out),str(case)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,f'{name} case {case}: '+result.stdout+result.stderr)

    def test_production_adapter_preserves_primask_and_union(self):
        out=feedback.guard.pair.binding.OUT.with_name('irq_adapter.exe')
        subprocess.run([feedback.guard.pair.binding.GCC,'-std=c11','-O2','-Wall','-Wextra',
            '-Werror','-pedantic','-UNDEBUG',*TRACE,
            '-I',str(ROOT/'tests/foc_irq_adapter_mock'),'-I',str(ROOT/'firmware_common'),
            str(ROOT/'tests/foc_irq_adapter_host.c'),str(ROOT/'firmware_common/foc_irq_load_stm32.c'),
            '-o',str(out)],check=True)
        subprocess.run([str(out)],check=True)

    def test_actual_adc_frame_closure_and_unchanged_feedback(self):
        results=[]
        for flags,name in ((feedback.FLAGS,'baseline'),(GATE,'gate'),(TRACE,'trace')):
            out=self.compile_host('tests/protected_adc_irq_host.c','irq_adc_'+name,flags)
            subprocess.run([str(out)],check=True)
            out=self.compile_host('tests/foc_pair_fast_host.c','irq_digest_'+name,flags)
            results.append(subprocess.run([str(out)],capture_output=True,text=True,check=True).stdout)
        self.assertEqual(len(set(results)),1)
        print(results[0].strip())

    def test_separate_presets_and_pinned_previous_images(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            for name,parent,key in (('ProtectedGateReuse','ProtectedFeedbackFast','FOC_GATE_REUSE'),
                                    ('ProtectedIrqSourceTrace','ProtectedGateReuse','FOC_IRQ_SOURCE_TRACE')):
                cfg=next(x for x in presets['configurePresets'] if x['name']==name)
                self.assertEqual(cfg['inherits'],parent)
                self.assertEqual(cfg['cacheVariables'],{key:'ON'})
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/ProtectedFeedbackFast/foc2.bin').read_bytes()).hexdigest(),
            '633a2735c3cf2e30dbc0cb19b5841b15981f9a2e08c297721ece41b751261659')
        for flags in (TRACE+['-UFOC_FEEDBACK_FAST_PATH'],TRACE+['-ffast-math']):
            result=subprocess.run([feedback.guard.pair.binding.GCC,'-std=c11','-fsyntax-only',
                '-I',str(ROOT/'firmware_common'),*flags,str(ROOT/'tests/foc_guard_integer_host.c')],capture_output=True)
            self.assertNotEqual(result.returncode,0)

    def test_real_linked_guardian_integer_only_in_both_profiles(self):
        for preset in ('ProtectedGateReuse','ProtectedIrqSourceTrace'):
            for slot in 'ab':
                elf=ROOT/f'foc2_app_{slot}/build/{preset}/foc2.elf'
                asm=subprocess.run([str(feedback.guard.ARM/'arm-none-eabi-objdump.exe'),'-d',str(elf)],
                    capture_output=True,text=True,check=True).stdout
                blocks={m.group(1):m.group(2) for m in re.finditer(
                    r'^[0-9a-f]+ <([^>]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)',asm,re.M|re.S)}
                seen=set(); pending=['TIM7_DAC_IRQHandler']
                while pending:
                    symbol=pending.pop()
                    if symbol in seen: continue
                    self.assertIn(symbol,blocks); seen.add(symbol); body=blocks[symbol]
                    self.assertNotRegex(body,r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s')
                    self.assertNotRegex(body,r'\t(?:blx|bx)\s+r[0-9]+\b')
                    self.assertNotIn('<memcpy>',body); self.assertNotIn('<__aeabi_',body)
                    pending.extend(re.findall(r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>',body))
                expected={'ProtectedLoop_EmergencyOff','ProtectedLoop_Stop','ProtectedLoop_GatesMatch'}
                expected.update(('FocIrqSource_Enter','FocIrqSource_Leave') if preset.endswith('Trace')
                                else ('FocIrqLoad_Enter','FocIrqLoad_Leave'))
                self.assertTrue(expected<=seen)
                self.assertNotIn('<memcpy>',blocks['ProtectedLoop_AdcIrq'])
                print(f'PASS {slot} {preset}: {len(seen)} linked integer-only guardian functions')


if __name__=='__main__': unittest.main()
