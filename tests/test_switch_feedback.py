from pathlib import Path
import sys
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import switch_feedback_acceptance as host
class SwitchFeedbackTests(unittest.TestCase):
    def test_host_output_and_count_gates(self):
        good='OK PROFILE=OPEN_LOAD_ONLY MOTOR_READY=0 ACTIVE=0 MODE=2 REASON=1 N=3600 FN=3598 US=180000 SD=0 MOE=0 CCER=0 CEN=0'
        host.require_switch(good,mode=2,complete=True)
        for old,new in (('SD=0','SD=1'),('MOE=0','MOE=1'),('N=3600','N=3599'),
                        ('REASON=1','REASON=2'),('US=180000','US=201000')):
            with self.subTest(old=old),self.assertRaises(RuntimeError):
                host.require_switch(good.replace(old,new),mode=2,complete=True)
    def test_host_one_shot_and_no_motion(self):
        class Port:
            def write(self,value): raise TimeoutError('simulated lost ACK')
        console=host.Console(Port())
        with self.assertRaises(TimeoutError): console.query('SWITCH START PWM')
        with self.assertRaises(ValueError): console.query('SWITCH START PWM')
        for text in ('START','CLEAR','BOOT B','FW CONFIRM'):
            with self.assertRaises(ValueError): console.query(text)
    def test_exact_reset_and_guard_vector(self):
        host.image()
    def test_actual_core(self):
        build=ROOT/'tests/foc_current_zero_build'; build.mkdir(exist_ok=True)
        exe=build/'switch_feedback_host.exe'
        subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe','-std=c11','-Wall','-Wextra',
                        '-Werror','-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),
                        str(ROOT/'tests/switch_feedback_host.c'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True,capture_output=True,text=True)
    def test_actual_guard_preparation_with_delayed_update(self):
        build=ROOT/'tests/foc_current_zero_build'; build.mkdir(exist_ok=True)
        exe=build/'switch_feedback_guard_host.exe'
        subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe','-std=c11','-Wall','-Wextra',
                        '-Werror','-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),
                        str(ROOT/'tests/switch_feedback_guard_host.c'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True,capture_output=True,text=True)
    def test_guard_vector_matches_silicon(self):
        code=(ROOT/'firmware_common/switch_feedback_diag.inc').read_text()
        for slot in 'ab':
            startup=(ROOT/f'foc2_app_{slot}/startup_stm32g474xx.s').read_text()
            self.assertIn('.word\tTIM7_DAC_IRQHandler',startup)
        self.assertIn('void TIM7_DAC_IRQHandler(void)',code)
        self.assertIn('TIM7_DAC_IRQn, 1U',code)
        self.assertIn('SwitchGuard_Prepare()',code)
        self.assertIn('zero_median.raw.state == FOC_ZERO_READY',code)
        self.assertIn('switch_wave_verified &&',code)
        self.assertNotIn('PowerStage_Enable(',code)
        self.assertNotIn('FOC_CurrentLoopStep(',code)
    def test_fault_handlers_off_first(self):
        for slot in 'ab':
            code=(ROOT/f'foc2_app_{slot}/Core/Src/stm32g4xx_it.c').read_text()
            for name in ('NMI','HardFault','MemManage','BusFault','UsageFault'):
                self.assertIn(f'void {name}_Handler(void)\n{{\n  SWITCH_FAULT_OFF();',code)
    def test_local_only_and_no_adc_reconfiguration_active(self):
        code=(ROOT/'firmware_common/zero_retest_boot.inc').read_text()
        self.assertLess(code.index('if (!protocol_esp_ping_uart_local)'),code.index('SwitchFeedback_Command(request_id'))
        self.assertIn('continue; /* No background ADC2 reconfiguration',code)
    def test_rtos_failures_shut_off_before_masking(self):
        for slot in 'ab':
            code=(ROOT/f'foc2_app_{slot}/Core/Inc/FreeRTOSConfig.h').read_text()
            self.assertLess(code.index('DIAGNOSTIC_ASSERT_OFF();'),code.index('taskDISABLE_INTERRUPTS();'))
        code=(ROOT/'firmware_common/switch_feedback_diag.inc').read_text()
        for hook in ('vApplicationMallocFailedHook','vApplicationStackOverflowHook'):
            body=code[code.index('void '+hook):]
            self.assertLess(body.index('SwitchFeedback_EmergencyOff('),body.index('__disable_irq();'))

if __name__=='__main__': unittest.main()
