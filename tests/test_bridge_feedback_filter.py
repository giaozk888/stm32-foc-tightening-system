from pathlib import Path
import subprocess
import unittest
import sys
import struct
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import filtered_bridge_acceptance as host
from test_feedback_safety_builds import symbols,CORE_HANDLERS
from test_six_signal_acceptance import reaches_switch_off
ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
class BridgeFeedbackTests(unittest.TestCase):
    def test_default_ab_has_no_bridge_fixture(self):
        for slot in 'ab':
            build=ROOT/f'foc2_app_{slot}/build/FilteredBridgeDefaultCheck20261013'
            cache=(build/'CMakeCache.txt').read_text('utf-8')
            self.assertIn('SWITCH_FILTERED_BRIDGE_DIAGNOSTIC:BOOL=OFF',cache)
            self.assertNotIn(b'DISCONNECTED_50MS',(build/'foc2.bin').read_bytes())
            self.assertNotIn('SwitchFeedback_EmergencyOff',symbols(build/'foc2.elf'))
    def test_linked_fixture_and_fault_routes(self):
        data=host.image(); build=host.IMAGE.parent; elf=build/'foc2.elf'; sym=symbols(elf)
        self.assertEqual(sym['TIM7_DAC_IRQHandler'][1],'T')
        self.assertEqual(struct.unpack_from('<I',data,(16+55)*4)[0],sym['TIM7_DAC_IRQHandler'][0]|1)
        for handler in (*CORE_HANDLERS,'HAL_ADC_ErrorCallback','vApplicationMallocFailedHook',
                        'vApplicationStackOverflowHook','Error_Handler'):
            self.assertTrue(reaches_switch_off(elf,handler),handler)
        cache=(build/'CMakeCache.txt').read_text('utf-8')
        for option in ('SWITCH_FILTERED_BRIDGE_DIAGNOSTIC','ZERO_RETEST_BOOT',
                       'SWITCH_FEEDBACK_DIAGNOSTIC','ZERO_MEDIAN_DIAGNOSTIC','UART_FIRMWARE_TRANSFER'):
            self.assertIn(option+':BOOL=ON',cache)
        for option in ('SWITCH_SIGNAL_ONLY_DIAGNOSTIC','FOC_ISOLATED_CONCURRENCY',
                       'FOC_ZERO_MEDIAN_COMPUTE_ONLY','CAN_MOTOR_CONTROL_SERVICE'):
            self.assertIn(option+':BOOL=OFF',cache)
    def test_host_no_retry_or_motor_commands(self):
        class Port:
            def write(self,data): raise TimeoutError('lost ACK')
        for capture in (False,True):
            console=host.Console(Port(),capture=capture)
            for cmd in ('START','CLEAR','SWITCH START BRIDGE','FW CONFIRM','BOOT A'):
                with self.assertRaises(ValueError): console.query(cmd)
            if capture:
                with self.assertRaises(ValueError): console.command('FW END')
                for cmd in ('ZERO SAMPLE','SWITCH START FILTERED_BRIDGE','SWITCH WAVE VERIFIED'):
                    with self.assertRaises(TimeoutError): console.query(cmd)
                    with self.assertRaises(ValueError): console.query(cmd)
            else:
                for cmd in ('ZERO SAMPLE','SWITCH START FILTERED_BRIDGE','SWITCH START OFF'):
                    with self.assertRaises(ValueError): console.query(cmd)
    def test_feedback_identity_does_not_claim_hardware_pass(self):
        good=('PROFILE=DISCONNECTED_50MS MOTOR_READY=0 RAW=VALIDITY_ONLY FILTERED=4A_2OF3 '
              'REPAIR_BUDGET=6/4 MAX_US=50000 DEADLINE_US=100 GUARD_US=25 '
              'WAVE_SOURCE=USER_ATTESTED HARDWARE_TRIP_VERIFIED=0')
        host.feedback(good)
        for old,new in (('USER_ATTESTED','AUTOMATIC_PASS'),('MAX_US=50000','MAX_US=100000'),
                        ('HARDWARE_TRIP_VERIFIED=0','HARDWARE_TRIP_VERIFIED=1')):
            with self.assertRaises(RuntimeError): host.feedback(good.replace(old,new))
    def test_periodic_guard_must_be_measured_outputs_off(self):
        good=('PROFILE=OPEN_LOAD_ONLY MOTOR_READY=0 ACTIVE=0 MODE=6 REASON=2 N=0 '
              'SD=0 MOE=0 CCER=0 CEN=0 IRQ=2000 US=50001 DONE=80 IRQ_SR=1')
        host.filtered_guard_result(good)
        for old,new in (('IRQ=2000','IRQ=1999'),('US=50001','US=100000'),
                        ('SD=0','SD=1'),('DONE=80','DONE=16')):
            with self.assertRaises(RuntimeError): host.filtered_guard_result(good.replace(old,new))
    def test_shared_core(self):
        build=ROOT/'tests/foc_current_zero_build'; build.mkdir(exist_ok=True)
        exe=build/'bridge_feedback_filter_host.exe'
        subprocess.run([GCC,'-std=c11','-Wall','-Wextra','-Werror','-pedantic',
            '-DFOC_PROTECTION_HOST_TEST=1','-UNDEBUG','-I',str(ROOT/'firmware_common'),
            str(ROOT/'tests/bridge_feedback_filter_host.c'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True,capture_output=True,text=True)
    def test_explicit_fixture_only(self):
        for slot in 'ab':
            code=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertIn('SWITCH_FILTERED_BRIDGE_DIAGNOSTIC',code)
            self.assertIn('NOT SWITCH_FEEDBACK_DIAGNOSTIC OR SWITCH_SIGNAL_ONLY_DIAGNOSTIC',code)
        code=(ROOT/'firmware_common/switch_feedback_diag.inc').read_text()
        for text in ('switch_irq_count>=2000U','now>=BRIDGE_FILTER_MAX_US',
                     'SwitchFilteredGuard_Arm()', 'SWITCH_WORK_LATE',
                     'HARDWARE_TRIP_VERIFIED=0','WAVE_SOURCE=USER_ATTESTED'):
            self.assertIn(text,code)
        self.assertNotIn('FOC_CurrentLoopStep(',code)
        self.assertNotIn('PowerStage_Enable(',code)
        wrapper=(ROOT/'firmware_common/foc_feedback_safety_candidate.h').read_text()
        self.assertIn('SWITCH_FEEDBACK_DIAGNOSTIC',wrapper) # hard-off binding not relaxed
if __name__=='__main__': unittest.main()
