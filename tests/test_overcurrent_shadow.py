"""Observe-only protection contracts; no powered protection qualification."""
from pathlib import Path
import sys
import unittest
import test_median_control_integration as binding
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import overcurrent_shadow_capture as capture

class OvercurrentShadowTests(unittest.TestCase):
    def test_capture_tool_cannot_mutate_or_sample(self):
        uart=capture.ObserverConsole(None)
        for text in ('FW END','START','CLEAR','FW RESET','BENCH STOP','ZERO SAMPLE'):
            with self.assertRaises(ValueError): uart.command(text)
            with self.assertRaises(ValueError): uart.query(text)
        calls=[]
        class Fake:
            def query(self,text):
                calls.append(text)
                if text=='OC SHADOW STATUS': return 'MODE=OBSERVE LIMIT_MA=4000 PEND=1'
                if text=='OC FILTER STATUS': return 'MODE=OBSERVE PAIRS=10 CHANGED=7 CU=5 CV=3'
                if text=='FAULT SNAPSHOT': return 'VALID=1 REASON=1 UP=2400 VP=1560'
                if text=='FAULT FILTER': return 'VALID=1'
                if text=='FAULT SHADOW': return 'VALID=1 MODE=OBSERVE SRC=1 RM=5 FM=0'
                if text=='FAULT TREND': return 'VALID=1 CHANGED=7'
                raise AssertionError(text)
        record={}; self.assertTrue(capture.capture_once(Fake(),record))
        self.assertEqual(record['trial_fault_captures'][0]['trend']['CHANGED'],'7')
        self.assertTrue(set(calls)<=capture.READ)

    def test_actual_c_state_machine(self):
        binding.MedianControlTests().compile_run('oc_shadow',['tests/foc_overcurrent_shadow_host.c'])

    def test_actual_frozen_capture_and_bounded_protocol(self):
        binding.MedianControlTests().compile_run('oc_shadow_capture',
            ['tests/foc_overcurrent_shadow_capture_host.c'],
            ['-DFOC_CURRENT_TREND4=1','-DFOC_CURRENT_SPIKE_ONLY=1'])

    def test_ab_integration_cannot_delay_or_suppress_hard_trip(self):
        for slot in 'ab':
            src=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            begin=src.index('static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,\n')
            fn=src[begin:src.index('static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s)\n{',begin)]
            trip=fn[fn.index('    if (\n#if defined(FOC_CURRENT_TREND4)\n'):]
            self.assertLess(trip.index('GPIO_PIN_RESET);'),trip.index('FocOcShadow_Push'))
            self.assertLess(trip.index('PWM_SetDuty(0.5f, 0.5f, 0.5f);'),trip.index('FocOcShadow_Push'))
            self.assertLess(trip.index('#include "foc_overcurrent_shadow_capture.inc"'),trip.index('foc_current_trip_snapshot.valid = 1U;'))
            gate=trip[:trip.index('    {')]
            self.assertNotIn('shadow',gate)
            self.assertIn('physical_trip ||',gate)
            self.assertIn('#else\n        physical_trip ||\n#endif',gate)
            self.assertIn('FocRawObserve_StopRequired',gate)
            self.assertIn('IsolatedBench_Locked()',gate)
            self.assertIn('#if !defined(FOC_RAW_OBSERVE_ONLY)\n    if (physical_trip)',fn)
            self.assertIn('filtered_u_A=iu_A',fn)  # preserve before physical override
            self.assertIn('#include "foc_overcurrent_shadow_protocol.inc"',src)
            self.assertIn('foc_trend_u_changed=FocOcShadow_Inc',src)
            self.assertIn('if (spike_ready && spike_u<=ADC_FULL_SCALE &&\n                    spike_v<=ADC_FULL_SCALE && adc_fault==0U)',src)
        header=(ROOT/'firmware_common/foc_overcurrent_shadow.h').read_text()
        self.assertNotIn('malloc(',header)
        self.assertNotIn('TIM1->',header)
        self.assertNotIn('HAL_',header)

    def test_zero_transition_resets_observer_not_protection(self):
        src=(ROOT/'firmware_common/isolated_concurrency.inc').read_text()
        ready=src[src.index('if (isolated_zero.state == FOC_ZERO_READY)'):src.index('static void IsolatedZero_Snapshot')]
        self.assertIn('FocOcShadow_Begin(&foc_oc_shadow);',ready)
        self.assertIn('foc_trend_pairs=foc_trend_changed=foc_trend_u_changed=foc_trend_v_changed=0U;',ready)
        self.assertNotIn('foc_fault = 0',ready)

if __name__=='__main__': unittest.main()
