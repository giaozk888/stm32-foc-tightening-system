import json
import re
from pathlib import Path
import subprocess
import unittest
import test_protected_closed_loop as binding

ROOT=binding.ROOT
FLAGS=['-D'+x for x in binding.DEFINES]+[
    '-DFOC_FAST_MATH=1','-DAS5047P_DMA_IRQ_PREEMPT_ADC=1','-DFOC_PAIR_FAST_PATH=1']

class PairFastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        binding.OUT.parent.mkdir(exist_ok=True)
    def test_exact_selector_popcount_and_full_feedback_equivalence(self):
        results=[]
        for fast in (False,True):
            out=binding.OUT.with_name('pair_equivalence_'+str(fast)+'.exe')
            flags=FLAGS if fast else FLAGS[:-1]
            subprocess.run([binding.GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',str(ROOT/'firmware_common'),*flags,
                str(ROOT/'tests/foc_pair_fast_host.c'),'-o',str(out)],check=True)
            p=subprocess.run([str(out)],capture_output=True,text=True,check=True)
            results.append(p.stdout)
        self.assertEqual(results[0],results[1])
        print(results[1].strip())
    def test_actual_binding_all_34_cases_and_first_late_not_overwritten(self):
        binding.ProtectedLoopTests.setUpClass()
        out=binding.OUT.with_name('protected_pair_fast.exe')
        subprocess.run(binding.ProtectedLoopTests.base+FLAGS+['-o',str(out)],check=True)
        for case in range(34):
            p=subprocess.run([str(out),str(case)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def test_actual_irq_retains_new_completion_and_same_frame_cost(self):
        out=binding.OUT.with_name('pair_adc.exe')
        subprocess.run([binding.GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-pedantic',
            '-UNDEBUG','-I',str(ROOT/'firmware_common'),*FLAGS,
            str(ROOT/'tests/protected_adc_irq_host.c'),'-o',str(out)],check=True)
        subprocess.run([str(out)],check=True)
    def test_all_existing_filtered_protection_scenarios(self):
        out=binding.OUT.with_name('pair_protection.exe')
        subprocess.run([binding.GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-pedantic',
            '-UNDEBUG','-I',str(ROOT/'firmware_common'),*FLAGS,
            str(ROOT/'tests/foc_filtered_protection_candidate_host.c'),'-o',str(out)],check=True)
        for case in range(9):
            p=subprocess.run([str(out),str(case)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def test_config_scope_guards_and_preserved_budgets(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            candidate=next(p for p in presets['configurePresets'] if p['name']=='ProtectedPairFast')
            self.assertEqual(candidate['inherits'],'ProtectedFastMath')
            self.assertEqual(candidate['cacheVariables'],{'FOC_PAIR_FAST_PATH':'ON'})
        source=ROOT/'tests/foc_pair_fast_host.c'
        base=[binding.GCC,'-std=c11','-fsyntax-only','-I',str(ROOT/'firmware_common'),str(source)]
        for drop in ('FOC_FAST_MATH=1','FOC_PROTECTED_CLOSED_LOOP=1','AS5047P_DMA_IRQ_PREEMPT_ADC=1'):
            p=subprocess.run(base+[f for f in FLAGS if f!='-D'+drop],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
        p=subprocess.run(base+FLAGS+['-ffast-math'],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        text=(ROOT/'firmware_common/protected_closed_loop.inc').read_text('utf-8')
        self.assertIn('if (elapsed>=50U)',text)
        self.assertIn('ProtectedLoop_EmergencyOff(CL_COMPUTE_LATE);',text)
        self.assertLess(text.index('ProtectedLoop_EmergencyOff(CL_COMPUTE_LATE);'),text.index('cl_late_cost=cl_frame_cost;'))
    def test_arm_popcount_fixed_straight_line_no_helper_call(self):
        out=binding.OUT.with_name('pair_popcount_arm.o')
        arm=Path('D:/software/arm/bin')
        subprocess.run([str(arm/'arm-none-eabi-gcc.exe'),'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-mcpu=cortex-m4','-mfloat-abi=hard','-mfpu=fpv4-sp-d16',
            '-I',str(ROOT/'firmware_common'),*FLAGS,'-c',
            str(ROOT/'tests/foc_pair_popcount_probe.c'),'-o',str(out)],check=True)
        undefined=subprocess.run([str(arm/'arm-none-eabi-nm.exe'),'-u',str(out)],
            check=True,capture_output=True,text=True).stdout
        self.assertEqual(undefined.strip(),'')
        asm=subprocess.run([str(arm/'arm-none-eabi-objdump.exe'),'-d',str(out)],
            check=True,capture_output=True,text=True).stdout
        # The reduction must be straight-line: no branch back to a loop or
        # branch/link to an ABI helper. bx lr (return) is the only branch.
        branches=re.findall(r'\t(b[a-z]+)(?:\.[nw])?\s+',asm)
        self.assertEqual(branches,['bx'])

if __name__=='__main__': unittest.main()
