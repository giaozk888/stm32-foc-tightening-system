"""Local compilation and mocks only. Never open UART, SWD, or a motor."""
from pathlib import Path
import hashlib
import re
import subprocess
import unittest
import test_feedback_safety_binding as guardian
import test_feedback_safety_builds as linked

ROOT = Path(__file__).resolve().parents[1]
GCC = r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
BUILD = ROOT / 'tests/foc_current_zero_build'
DEFINES = ['-D' + x + '=1' for x in guardian.REQUIRED] + ['-DFOC_CONTROL_CHAIN_RECONNECT=1']

class ReconnectAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BUILD.mkdir(exist_ok=True)
        cls.exe = BUILD / 'control_chain_reconnect.exe'
        subprocess.run([GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                        '-UNDEBUG', *DEFINES, '-I', str(ROOT/'firmware_common'),
                        str(ROOT/'tests/control_chain_reconnect_host.c'), '-o', str(cls.exe)], check=True)

    def case(self, n):
        p = subprocess.run([str(self.exe),str(n)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_speed_command_is_consumed_only_by_application_owner(self): self.case(0)
    def test_iq_and_stop_clear_reference_without_rearming(self): self.case(1)
    def test_tighten_uses_original_start_mailbox_once(self): self.case(2)
    def test_wrong_correlation_cannot_inherit_diagnostic_admission(self): self.case(3)
    def test_fixed_5000ms_expiry_stops_and_cannot_retry(self): self.case(4)
    def test_health_freshness_zero_and_trial_rejection(self): self.case(5)
    def test_queued_command_is_revalidated_at_consumption(self): self.case(6)
    def test_fault_and_lock_loss_cancel_active_control(self): self.case(7)
    def test_unknown_setpoint_rejected_and_deadline_wrap(self): self.case(8)
    def test_counter_staleness_and_late_start_fault(self): self.case(9)
    def test_independent_microsecond_lease_deadline(self): self.case(10)

    def test_actual_guardian_interrupt_ends_expired_control_lease(self):
        exe=BUILD/'control_chain_guardian.exe'
        subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic',
                        '-UNDEBUG',*DEFINES,'-I',str(ROOT/'firmware_common'),
                        str(ROOT/'tests/foc_feedback_binding_host.c'),'-o',str(exe)],check=True)
        p=subprocess.run([str(exe),'8'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_actual_ab_current_pi_uses_filtered_frame_and_original_limits(self):
        macros=('TWO_PI_F','ADC_VREF_MV','ADC_FULL_SCALE','CURRENT_GAIN_MV_PER_A',
                'FOC_TS_S','FOC_CURRENT_KP_V_PER_A','FOC_CURRENT_KI_V_PER_AS',
                'FOC_DC_BUS_V','FOC_VOLTAGE_LIMIT_V','FOC_INTEGRATOR_LIMIT_V')
        for slot in 'ab':
            src=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            first=src.index('static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,\n')
            last=src.index('\n\n/*\n * Update AS5047P,',first)
            # Generated test-build inputs, never edit the application algorithm.
            (BUILD/'control_chain_current_body.inc').write_text(src[first:last],encoding='utf-8')
            definitions=[re.search(r'^#define '+name+r'\s+.*$',src,re.M).group(0) for name in macros]
            (BUILD/'control_chain_current_constants.inc').write_text('\n'.join(definitions)+'\n',encoding='utf-8')
            exe=BUILD/f'control_chain_current_{slot}.exe'
            subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic',
                            '-UNDEBUG',*DEFINES,'-I',str(BUILD),'-I',str(ROOT/'firmware_common'),
                            str(ROOT/'tests/control_chain_current_loop_host.c'),'-o',str(exe)],check=True)
            for n in range(4):
                p=subprocess.run([str(exe),str(n)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,f'{slot}/{n}: '+p.stdout+p.stderr)

    def test_ab_original_loop_and_task_binding_contracts(self):
        for slot in 'ab':
            src=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            self.assertIn('#include "control_chain_reconnect.inc"',src)
            self.assertIn('ControlChain_TaskService();',src)
            self.assertIn('ControlChain_StartReady(start_request_id)',src)
            self.assertIn('if (protocol_reply_route_active || !protocol_esp_ping_uart_local)',src)
            self.assertIn('HAL_StatusTypeDef update = FOC_EncoderSpeedUpdate(0.001f);',src)
            # Normal motor admission stays unchanged: the diagnostic never sets foc_enable.
            self.assertIn('if (foc_enable == 0U) mask |= PREFLIGHT_FAIL_FOC_DISABLED;',src)
            for text in ('FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw, u, v);',
                         'err_q = foc_iq_ref_A - iq_A;',
                         'iu_A = foc_feedback_control_frame.iu_A;',
                         'theta = foc_feedback_control_frame.measurement_angle;',
                         'sinf(foc_feedback_control_frame.actuation_angle)',
                         'else if (mode == MOTOR_MODE_IQ)'):
                self.assertTrue(text in src,text)
            self.assertTrue(re.search(r'tightening_test_stage\s*=\s*TIGHTEN_STATE_RUNDOWN;',src))
            for fn in ('PowerStage_Enable','PWM_StartAll','PWM_SetDuty'):
                start=src.index('static void '+fn+'(',src.index('static void PowerStage_Disable(void)\n{'))
                body=src[start:src.index('\nstatic ',start+1)]
                self.assertIn('#if defined(FOC_ISOLATED_CONCURRENCY)',body)
                self.assertIn('return;',body)

    def test_actual_linked_ab_tasks_guard_vector_and_read_only_profile(self):
        for slot in 'ab':
            folder=ROOT/f'foc2_app_{slot}/build/ControlChainReconnect'
            syms=linked.symbols(folder/'foc2.elf')
            for name in ('MotorControlTask','TighteningTask','FocFeedbackBinding_EmergencyOff'):
                self.assertIn(name,syms)
            self.assertEqual(syms['TIM7_DAC_IRQHandler'][1],'T')
            cache=(folder/'CMakeCache.txt').read_text('utf-8')
            for name in guardian.REQUIRED+('FOC_CONTROL_CHAIN_RECONNECT',):
                self.assertIn(name+':BOOL=ON',cache)
            for name in guardian.FORBIDDEN+('CAN_MOTOR_CONTROL_SERVICE','CAN_FD_EXPERIMENT'):
                self.assertIn(name+':BOOL=OFF',cache)
            image=(folder/'foc2.bin').read_bytes()
            self.assertLessEqual(len(image),224*1024)
            self.assertIn(b'BENCH CHAIN TIGHTEN',image)
            self.assertIn(b'HARD_OFF=1 MOTOR_QUALIFIED=0',image)
            self.assertIn(b'TIGHTEN: START -> RUNDOWN',image)

    def test_deployed_b463_and_a460_local_images_preserved(self):
        images={
            'foc2_app_a/build/SixSignalQualification20261013/foc2.bin':
            '8769374cec2038667aa505bbfbd909b5ddb2010d95dccbbb2294a498aad1fe45',
            'foc2_app_b/build/FilteredBridge20261013/foc2.bin':
            'eb13779af465650dc7a82ac99b0a494e1e0796bb783a2e76b5b10020d4779ca9',
        }
        for name,digest in images.items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)

    def test_fresh_default_builds_exclude_reconnection(self):
        for slot in 'ab':
            folder=ROOT/f'foc2_app_{slot}/build/ControlChainDefaultCheck'
            self.assertIn('FOC_CONTROL_CHAIN_RECONNECT:BOOL=OFF',(folder/'CMakeCache.txt').read_text('utf-8'))
            syms=linked.symbols(folder/'foc2.elf')
            self.assertFalse(any('ControlChain_' in name for name in syms))
            self.assertNotIn('FocFeedbackBinding_EmergencyOff',syms)
            self.assertNotIn(b'BENCH CHAIN TIGHTEN',(folder/'foc2.bin').read_bytes())
            prior=ROOT/f'foc2_app_{slot}/build/FilteredBridgeDefaultCheck20261013/foc2.bin'
            self.assertEqual((folder/'foc2.bin').read_bytes(),prior.read_bytes())

    def test_reconnect_cannot_be_configured_without_hard_off_binding(self):
        cmake=r'C:\Program Files\CMake\bin\cmake.exe'
        toolchain=ROOT/'foc2_app_b/cmake/gcc-arm-none-eabi.cmake'
        folder=BUILD/'reconnect_rejected_config'
        p=subprocess.run([cmake,'-S',str(ROOT/'foc2_app_b'),'-B',str(folder),'-G','Ninja',
                          '-DCMAKE_TOOLCHAIN_FILE='+str(toolchain),
                          '-DCMAKE_C_COMPILER=D:/software/arm/bin/arm-none-eabi-gcc.exe',
                          '-DCMAKE_CXX_COMPILER=D:/software/arm/bin/arm-none-eabi-g++.exe',
                          '-DCMAKE_ASM_COMPILER=D:/software/arm/bin/arm-none-eabi-gcc.exe',
                          '-DCMAKE_MAKE_PROGRAM=D:/software/ninja/ninja.exe',
                          '-DFOC_CONTROL_CHAIN_RECONNECT=ON','-DFOC_FEEDBACK_SAFETY_BINDING=OFF'],
                         capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Control chain reconnect requires hard-off feedback binding',p.stdout+p.stderr)

if __name__=='__main__': unittest.main()
