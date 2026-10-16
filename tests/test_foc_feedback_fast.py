import hashlib
import json
import re
import subprocess
import unittest
import test_foc_guard_fast as guard

ROOT=guard.ROOT
FLAGS=guard.FLAGS+['-DFOC_FEEDBACK_FAST_PATH=1']


class FeedbackFastTests(unittest.TestCase):
    ELF_PRESET='ProtectedFeedbackFast'
    @classmethod
    def setUpClass(cls): guard.pair.binding.ProtectedLoopTests.setUpClass()

    def compile_host(self,source,name,flags=FLAGS,opt='-O2'):
        out=guard.pair.binding.OUT.with_name(name+'.exe')
        subprocess.run([guard.pair.binding.GCC,'-std=c11',opt,'-Wall','-Wextra',
            '-Werror','-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),
            *flags,str(ROOT/source),'-o',str(out)],check=True)
        return out

    def test_feedback_digest_identical_at_os_and_o2(self):
        results=[]
        for opt in ('-Os','-O2'):
            for fast in (False,True):
                out=self.compile_host('tests/foc_pair_fast_host.c',
                    'feedback_equivalence_'+opt+'_'+str(fast),FLAGS if fast else guard.FLAGS,opt)
                results.append(subprocess.run([str(out)],capture_output=True,text=True,check=True).stdout)
        self.assertTrue(all(x==results[0] for x in results))
        print(results[0].strip())

    def test_actual_binding_all_41_cases(self):
        out=guard.pair.binding.OUT.with_name('protected_feedback_fast.exe')
        subprocess.run(guard.pair.binding.ProtectedLoopTests.base+FLAGS+['-o',str(out)],check=True)
        for case in range(41):
            result=subprocess.run([str(out),str(case)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_public_protection_and_actual_adc_entry(self):
        out=self.compile_host('tests/foc_filtered_protection_candidate_host.c','feedback_protection')
        for case in range(9): subprocess.run([str(out),str(case)],check=True,capture_output=True)
        out=self.compile_host('tests/protected_adc_irq_host.c','feedback_adc')
        subprocess.run([str(out)],check=True)

    def test_integer_guard_equivalence(self):
        out=self.compile_host('tests/foc_guard_integer_host.c','feedback_integer')
        subprocess.run([str(out)],check=True)

    def test_real_linked_guardian_still_integer_only(self):
        guard.GuardFastTests.test_linked_guardian_has_no_vfp_or_hidden_calls(self)

    def test_arm_no_outlined_feedback_or_selector_calls(self):
        for slot in 'ab':
            elf=ROOT/f'foc2_app_{slot}/build/{self.ELF_PRESET}/foc2.elf'
            symbols=subprocess.run([str(guard.ARM/'arm-none-eabi-nm.exe'),str(elf)],
                capture_output=True,text=True,check=True).stdout
            self.assertNotRegex(symbols,r'\b(?:FocFeedbackSafety_(?:Push|Poll|Take)|'
                r'FocFp_(?:Push|PushAfterPoll|Poll|Trip)|FocTrend4_(?:Isolated|Distance))\b')
            assembly=subprocess.run([str(guard.ARM/'arm-none-eabi-objdump.exe'),'-d',
                '--disassemble=ProtectedLoop_AdcIrq',str(elf)],
                capture_output=True,text=True,check=True).stdout
            self.assertIn('<ProtectedLoop_AdcIrq>:',assembly)
            self.assertNotRegex(assembly,r'\t(?:bl|blx|b\.w)\s+[^<]*<Foc(?:FeedbackSafety|Fp|Trend4)_')
            self.assertNotIn('<memcpy>',assembly)

    def test_separate_opt_in_original_budget_and_pinned_images(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            cfg=next(x for x in presets['configurePresets'] if x['name']==self.ELF_PRESET)
            self.assertEqual(cfg['inherits'],'ProtectedGuardFast')
            self.assertEqual(cfg['cacheVariables'],{'FOC_FEEDBACK_FAST_PATH':'ON'})
        for key in ('if (elapsed>=50U)','HAL_NVIC_SetPriority(TIM7_DAC_IRQn,0U,0U)',
                    'HAL_NVIC_SetPriority(ADC1_2_IRQn,2U,0U)'):
            self.assertIn(key,(ROOT/'firmware_common/protected_closed_loop.inc').read_text('utf-8'))
        for flags in (FLAGS+['-UFOC_GUARD_FAST_PATH'],FLAGS+['-ffast-math']):
            result=subprocess.run([guard.pair.binding.GCC,'-std=c11','-fsyntax-only',
                '-I',str(ROOT/'firmware_common'),*flags,str(ROOT/'tests/foc_guard_integer_host.c')],
                capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
        pinned={
            'ProtectedGuardFast':'6a0957d0a54653aeea8374a062ef245676967f165cf33347c9cde3d9f93e07ef',
            'ProtectedPairFast':'a8117c7fda8b10887b79b6dd070a044f29d97a0e2776db5a18cdfb9cf60e80ec'}
        for preset,sha in pinned.items():
            self.assertEqual(hashlib.sha256((ROOT/f'foc2_app_b/build/{preset}/foc2.bin').read_bytes()).hexdigest(),sha)


if __name__=='__main__': unittest.main()
