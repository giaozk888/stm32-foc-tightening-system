from pathlib import Path
import json
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'

class OptimizedIrqTests(unittest.TestCase):
    def test_new_build_directory_preserves_previous_pinned_images(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            profile=next(p for p in presets['configurePresets'] if p['name']=='ProtectedIrqOptimized')
            self.assertEqual(profile['inherits'],'ProtectedClosedLoop')
            self.assertNotIn('cacheVariables',profile)
            default=next(p for p in presets['configurePresets'] if p['name']=='default')
            self.assertEqual(default['binaryDir'],'${sourceDir}/build/${presetName}')

    def test_actual_early_ack_entry_and_error_paths(self):
        out=ROOT/'tests/foc_current_zero_build/protected_irq.exe'
        out.parent.mkdir(exist_ok=True)
        subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                        '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/protected_adc_irq_host.c'),
                        '-o',str(out)],check=True)
        subprocess.run([str(out)],check=True)

    def test_production_dispatch_has_no_hal_tail_clear_on_fast_path(self):
        fast=(ROOT/'firmware_common/protected_adc_irq.inc').read_text('utf-8')
        ack=fast.index('__HAL_ADC_CLEAR_FLAG(&hadc1')
        compute=fast.index('FOC_CurrentLoopStep(')
        self.assertLess(ack,compute)
        self.assertNotIn('__HAL_ADC_CLEAR_FLAG',fast[compute:])
        self.assertIn('if (ProtectedLoop_Pair(u,v))',fast)
        self.assertIn('ProtectedLoop_WorkEnd(protected_begin);',fast)
        self.assertLess(fast.index('ProtectedLoop_EmergencyOff'),fast.index('HAL_ADC_IRQHandler'))
        for slot in 'ab':
            irq=(ROOT/f'foc2_app_{slot}/Core/Src/stm32g4xx_it.c').read_text('utf-8')
            branch=irq[irq.index('void ADC1_2_IRQHandler'):]
            protected=branch[branch.index('#if defined(FOC_PROTECTED_CLOSED_LOOP)'):branch.index('#else')]
            self.assertIn('ProtectedLoop_AdcIrq();',protected)
            self.assertNotIn('HAL_ADC_IRQHandler',protected)
            main=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            self.assertEqual(main.count('#include "protected_adc_irq.inc"'),1)

    def test_planning_precedes_mask_and_hot_guard_has_no_frequency_walk(self):
        binding=(ROOT/'firmware_common/protected_closed_loop.inc').read_text('utf-8')
        duty=binding[binding.index('static void ProtectedLoop_SetDuty'):binding.index('static void ProtectedLoop_TaskService')]
        self.assertLess(duty.index('FocAdcTiming_Prepare('),duty.index('__disable_irq()'))
        self.assertLess(duty.index('cl_session.state==CL_RUNNING'),duty.index('FocAdcTiming_CommitPrepared'))
        task=binding[binding.index('static void ProtectedLoop_TaskService'):binding.index('static void ProtectedLoop_Command')]
        self.assertLess(task.index('FocAdcTiming_Prepare('),task.index('__disable_irq()'))
        # The helper may be FOC_COMPACT_HELPER/always-inline, or the captured
        # health variant when gate reuse is enabled; storage spelling is not
        # the behavior this check is intended to verify.
        health=binding[binding.index('uint32_t ProtectedLoop_Health'):binding.index('static int ProtectedLoop_Pair')]
        self.assertIn('FocAdcTiming_FastCanStart()',health)
        self.assertNotIn('FocAdcTiming_CanStart()',health)
        adapter=(ROOT/'firmware_common/foc_adc_timing_stm32.c').read_text('utf-8')
        fast=adapter[adapter.index('int FocAdcTiming_FastCanStart'):adapter.index('int FocAdcTiming_PairReady')]
        self.assertNotIn('HAL_RCC_Get',fast)
        self.assertIn('ClockEqual(clock_proof, ClockRead())',fast)

if __name__=='__main__': unittest.main()
