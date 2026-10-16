import json
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
class FastMathTests(unittest.TestCase):
    def test_production_numerics_and_nested_irq_counter(self):
        out=ROOT/'tests/foc_current_zero_build/fast_math.exe'
        out.parent.mkdir(exist_ok=True)
        subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/foc_fast_math_host.c'),
            str(ROOT/'firmware_common/foc_fast_trig.c'),'-o',str(out)],check=True)
        subprocess.run([str(out)],check=True)
    def test_separate_candidate_and_fault_policy(self):
        branches=[]
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            fast=next(p for p in presets['configurePresets'] if p['name']=='ProtectedFastMath')
            self.assertEqual(fast['inherits'],'ProtectedIrqPriorityFix')
            self.assertEqual(fast['cacheVariables'],{'FOC_FAST_MATH':'ON'})
            main=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            begin=main.index('static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,\n')
            branch=main[begin:main.index('static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s)\n{',begin)]
            self.assertEqual(branch.count('FocFast_SinCos('),2)
            self.assertIn('ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); return;',branch)
            branches.append(branch)
        self.assertEqual(branches[0],branches[1])
        binding=(ROOT/'firmware_common/protected_closed_loop.inc').read_text('utf-8')
        self.assertIn('if (elapsed>=50U)',binding)
        self.assertIn('FocIrqLoad_Enter(); ProtectedLoop_GuardIrqBody(); FocIrqLoad_Leave();',binding)
        driver=(ROOT/'firmware_common/as5047p_dma_stm32.c').read_text('utf-8')
        for body in ('Rx','Tx','Timer'):
            self.assertIn(f'FocIrqLoad_Enter(); EncoderDma_{body}IrqBody(); FocIrqLoad_Leave();',driver)
    def test_arm_trig_has_no_libm_calls_or_fastmath(self):
        source=ROOT/'firmware_common/foc_fast_trig.c'
        out=ROOT/'tests/foc_current_zero_build/fast_trig_arm.o'
        subprocess.run([r'D:\software\arm\bin\arm-none-eabi-gcc.exe','-std=c11','-O2',
            '-mcpu=cortex-m4','-mfloat-abi=hard','-mfpu=fpv4-sp-d16','-Wall','-Wextra','-Werror',
            '-c',str(source),'-o',str(out)],check=True)
        result=subprocess.run([r'D:\software\arm\bin\arm-none-eabi-nm.exe','-u',str(out)],
                              check=True,capture_output=True,text=True)
        self.assertEqual(result.stdout.strip(),'')
        bad=subprocess.run([GCC,'-std=c11','-ffast-math','-fsyntax-only',str(source)],
                           capture_output=True,text=True)
        self.assertNotEqual(bad.returncode,0)
    def test_actual_adc_entry_cost_and_completion_order(self):
        out=ROOT/'tests/foc_current_zero_build/fast_math_adc.exe'
        subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
            '-DFOC_FAST_MATH=1','-I',str(ROOT/'firmware_common'),
            str(ROOT/'tests/protected_adc_irq_host.c'),'-o',str(out)],check=True)
        subprocess.run([str(out)],check=True)
    def test_actual_binding_keeps_all_guard_fault_paths(self):
        import test_protected_closed_loop as base
        base.ProtectedLoopTests.setUpClass()
        out=base.OUT.with_name('protected_loop_fast_math.exe')
        subprocess.run(base.ProtectedLoopTests.base+['-D'+x for x in base.DEFINES]+
            ['-DAS5047P_DMA_IRQ_PREEMPT_ADC=1','-DFOC_FAST_MATH=1','-o',str(out)],check=True)
        for case in range(32):
            p=subprocess.run([str(out),str(case)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

if __name__=='__main__': unittest.main()
