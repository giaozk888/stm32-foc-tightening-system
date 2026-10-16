import json
from pathlib import Path
import re
import subprocess
import unittest
import test_foc_pair_fast as pair

ROOT=pair.ROOT
FLAGS=pair.FLAGS+['-DFOC_GUARD_FAST_PATH=1']
ARM=Path('D:/software/arm/bin')


class GuardFastTests(unittest.TestCase):
    ELF_PRESET='ProtectedGuardFast'
    @classmethod
    def setUpClass(cls):
        pair.binding.ProtectedLoopTests.setUpClass()

    def compile_host(self,source,name,flags=FLAGS):
        out=pair.binding.OUT.with_name(name+'.exe')
        subprocess.run([pair.binding.GCC,'-std=c11','-O2','-Wall','-Wextra',
            '-Werror','-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),
            *flags,str(ROOT/source),'-o',str(out)],check=True)
        return out

    def test_integer_guard_binary32_and_boundaries(self):
        out=self.compile_host('tests/foc_guard_integer_host.c','guard_integer')
        subprocess.run([str(out)],check=True)

    def test_same_feedback_and_fault_digest(self):
        results=[]
        for flags,name in ((pair.FLAGS,'guard_reference'),(FLAGS,'guard_candidate')):
            out=self.compile_host('tests/foc_pair_fast_host.c',name,flags)
            results.append(subprocess.run([str(out)],capture_output=True,text=True,check=True).stdout)
        self.assertEqual(results[0],results[1])
        print(results[1].strip())

    def test_actual_guard_all_41_cases(self):
        out=pair.binding.OUT.with_name('protected_guard_fast.exe')
        subprocess.run(pair.binding.ProtectedLoopTests.base+FLAGS+['-o',str(out)],check=True)
        for case in range(41):
            p=subprocess.run([str(out),str(case)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_public_protection_entry_and_adc_entry(self):
        out=self.compile_host('tests/foc_filtered_protection_candidate_host.c','guard_protection')
        for case in range(9):
            subprocess.run([str(out),str(case)],check=True,capture_output=True)
        out=self.compile_host('tests/protected_adc_irq_host.c','guard_adc')
        subprocess.run([str(out)],check=True)

    def test_scoped_config_and_preserved_recheck(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            p=next(x for x in presets['configurePresets'] if x['name']=='ProtectedGuardFast')
            self.assertEqual(p['inherits'],'ProtectedPairFast')
            self.assertEqual(p['cacheVariables'],{'FOC_GUARD_FAST_PATH':'ON'})
        source=(ROOT/'firmware_common/protected_closed_loop.inc').read_text('utf-8')
        self.assertIn('if (elapsed>=50U)',source)
        self.assertIn('FocFeedbackSafety_Take(&cl_safety,AS5047P_DmaNowUs(),flags,',source)
        self.assertIn('HAL_NVIC_SetPriority(TIM7_DAC_IRQn,0U,0U)',source)
        self.assertIn('HAL_NVIC_SetPriority(ADC1_2_IRQn,2U,0U)',source)
        bad=subprocess.run([pair.binding.GCC,'-std=c11','-fsyntax-only',
            '-I',str(ROOT/'firmware_common'),*FLAGS,'-UFOC_PAIR_FAST_PATH',
            str(ROOT/'tests/foc_guard_integer_host.c')],capture_output=True)
        self.assertNotEqual(bad.returncode,0)

    def test_linked_guardian_has_no_vfp_or_hidden_calls(self):
        # Walk actual linked call/tail-call targets, including fault/STOP paths.
        # Poll may be inlined; a fixed list could miss a newly introduced callee.
        for slot in 'ab':
            elf=ROOT/f'foc2_app_{slot}/build/{self.ELF_PRESET}/foc2.elf'
            disassembly=subprocess.run([str(ARM/'arm-none-eabi-objdump.exe'),'-d',
                str(elf)],capture_output=True,text=True,check=True).stdout
            blocks={m.group(1):m.group(2) for m in re.finditer(
                r'^[0-9a-f]+ <([^>]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)',
                disassembly,re.M|re.S)}
            seen=set()
            pending=['TIM7_DAC_IRQHandler']
            while pending:
                symbol=pending.pop()
                if symbol in seen: continue
                self.assertIn(symbol,blocks)
                seen.add(symbol)
                result=blocks[symbol]
                self.assertNotRegex(result,r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s')
                self.assertNotRegex(result,r'\t(?:blx|bx)\s+r[0-9]+\b')
                self.assertNotIn('<memcpy>',result)
                self.assertNotIn('<__aeabi_',result)
                pending.extend(re.findall(
                    r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>',result))
            self.assertTrue({'ProtectedLoop_GuardIrqBody','ProtectedLoop_Health',
                'ProtectedLoop_EmergencyOff','ProtectedLoop_Stop',
                'ProtectedLoop_GatesMatch','FocIrqLoad_Enter','FocIrqLoad_Leave'}<=seen)
            print(f'PASS {slot.upper()} linked integer-only guardian: {len(seen)} functions')


if __name__=='__main__': unittest.main()
