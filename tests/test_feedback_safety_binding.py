"""Actual binding/register mock execution, plus unchanged normal-profile guards."""
from pathlib import Path
import subprocess
import unittest
import test_median_control_integration as binding

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/foc_feedback_binding_host.c'
OUT = ROOT / 'tests/foc_current_zero_build/feedback_binding.exe'
REQUIRED = ('FOC_FEEDBACK_SAFETY_BINDING', 'FOC_ISOLATED_CONCURRENCY',
            'FOC_ZERO_MEDIAN_COMPUTE_ONLY', 'FOC_ADC_WINDOW', 'AS5047P_SPI_DMA',
            'FOC_CURRENT_TREND4', 'FOC_CURRENT_SPIKE_ONLY')
FORBIDDEN = ('FOC_RAW_OBSERVE_ONLY', 'FOC_FILTERED_OBSERVE_ONLY', 'ZERO_RETEST_BOOT',
             'SWITCH_FEEDBACK_DIAGNOSTIC', 'FOC_ZERO_FAILURE_TRACE',
             'TIGHTEN_SYNTHETIC_BENCH', 'FOC_OC_LAYERED_SELFTEST')

class FeedbackBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.parent.mkdir(exist_ok=True)
        subprocess.run([binding.GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-pedantic', '-UNDEBUG', *['-D'+x+'=1' for x in REQUIRED],
                        '-I', str(ROOT / 'firmware_common'), str(SOURCE), '-o', str(OUT)], check=True)

    def run_case(self, n):
        p = subprocess.run([str(OUT), str(n)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

    def test_register_shutdown_and_first_fault_latch(self): self.run_case(0)
    def test_independent_timeout_without_any_adc_or_consumer_callback(self): self.run_case(1)
    def test_actual_filter_binding_warmup_and_confirmed_overcurrent(self): self.run_case(2)
    def test_stream_health_and_register_lock_loss(self): self.run_case(3)
    def test_timer_update_handshake_and_setup_fail_closed(self): self.run_case(4)
    def test_wrap_and_real_repair_quality_shutdown(self): self.run_case(5)
    def test_timing_budget_and_preserved_first_post_shutdown_snapshot(self): self.run_case(6)
    def test_stopped_stream_injection_is_hard_off_once_only(self): self.run_case(7)

    def test_compile_rejects_power_and_bypass_profiles(self):
        base = [binding.GCC, '-std=c11', '-fsyntax-only', '-I', str(ROOT / 'firmware_common'), str(SOURCE)]
        for missing in REQUIRED:
            for value in (None, 0):
                defines = ['-D'+x+'=1' for x in REQUIRED if x!=missing]
                if value is not None: defines.append('-D'+missing+'=0')
                p = subprocess.run(base+defines, capture_output=True, text=True)
                self.assertNotEqual(p.returncode, 0, (missing,value))
        for forbidden in FORBIDDEN:
            p = subprocess.run(base+['-D'+x+'=1' for x in REQUIRED]+['-D'+forbidden+'=1'],
                               capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0, forbidden)

    def test_ab_interrupt_lifecycle_and_default_protection_contracts(self):
        for slot in 'ab':
            src = (ROOT / f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            self.assertIn('FOC_FEEDBACK_SAFETY_BINDING', src)
            self.assertIn('FocFeedbackBinding_PhysicalSeen(u, v)', src)
            self.assertIn('FocFeedbackBinding_Control(u, v)', src)
            self.assertIn('FocFeedbackBinding_WorkEnd(feedback_start_us)', src)
            protocol = src[src.index('else if (strcmp(cmd, "BENCH RUN")'):src.index('else if (strcmp(cmd, "ANALOG SAFE STATUS")')]
            self.assertIn('"LOCAL_CONSOLE_ONLY"', protocol)
            self.assertIn('BootHealth_IsCurrentTrial() || !FocFeedbackBinding_TestTimeout()', protocol)
            self.assertIn('physical_trip ||', src)
            self.assertIn('foc_feedback_control_frame.measurement_angle', src)
            self.assertIn('sinf(foc_feedback_control_frame.actuation_angle)', src)
            for name,flag in [('EncoderDma_FaultFromISR','FOC_FB_ENCODER_INVALID'),
                              ('HAL_ADC_ErrorCallback','FOC_FP_ADC_INVALID'),
                              ('Error_Handler','FOC_FB_CORE_FAULT')]:
                start = src.index(('void ' if name!='EncoderDma_FaultFromISR' else 'static void ')+name+'(')
                self.assertIn('FocFeedbackBinding_EmergencyOff('+flag+')', src[start:start+350])
            irq = (ROOT / f'foc2_app_{slot}/Core/Src/stm32g4xx_it.c').read_text('utf-8')
            self.assertIn('FocFeedbackBinding_EmergencyOff(FOC_FB_CORE_FAULT)', irq)
            for name in ('NMI_Handler','HardFault_Handler','MemManage_Handler','BusFault_Handler','UsageFault_Handler'):
                fn = irq[irq.index('void '+name+'('):]
                self.assertIn('SWITCH_FAULT_OFF();', fn[:300])
            cmake = (ROOT / f'foc2_app_{slot}/CMakeLists.txt').read_text('utf-8')
            self.assertIn('Filtered confirmation and TIM7 shutdown in hard-off FOC fixture ONLY" OFF)', cmake)
        lifecycle = (ROOT / 'firmware_common/isolated_concurrency.inc').read_text('utf-8')
        for name in ('FocFeedbackBinding_Arm(nominal)', 'FocFeedbackBinding_Disarm()',
                     'FocFeedbackBinding_ZeroReady()', 'FocFeedbackBinding_TimerHealthy()'):
            self.assertIn(name, lifecycle)
        candidate = (ROOT / 'firmware_common/foc_feedback_binding_stm32.inc').read_text('utf-8')
        self.assertNotIn('TIM2->CCR', candidate)  # Clock only, encoder ownership unchanged.
        self.assertNotIn('xTask', candidate)
        self.assertNotIn('UART_Send', candidate)

if __name__ == '__main__': unittest.main()
