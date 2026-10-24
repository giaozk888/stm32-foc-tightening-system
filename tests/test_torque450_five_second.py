"""450mA opt-in owner; files/mocks only, never hardware."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque450_five_second_acceptance as acceptance


class Torque450Tests(unittest.TestCase):
    def test_actual_positive_only_owner_five_second_lease_and_fault_races(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/('tests/torque_chain_build/torque450'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_TORQUE450_FIVE_SECOND=1','-DFOC_TORQUE_CHAIN_IQ_MA=450',
                '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
                str(ROOT/'tests/torque_chain_host.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_actual_setter_and_outer_have_matching_450ma_clamp(self):
        for slot in 'ab':
            source=expanded(slot,'Torque450mAFiveSecondDiagnostic')
            setter=function(source,'MotorControl_SetIq')
            outer=function(source,'FOC_EncoderSpeedUpdate')
            assignment=re.search(r'foc_iq_ref_A\s*=\s*ClampFloat\(motor_iq_command_A,\s*-0.45f,\s*0.45f\);',outer)
            self.assertIsNotNone(assignment)
            code='''#include <assert.h>
#include <math.h>
#define MOTOR_MODE_IQ 3
static unsigned motor_control_mode,motor_position_active_hold;
static float motor_iq_command_A,motor_speed_command_rpm,foc_iq_ref_A;
static void ProtectedLoop_PwmInvalidate(void) {}
'''
            code+='static float '+function(source,'ClampFloat')+'\nstatic void '+setter+'\n'
            code+='static void outer(void) {'+assignment.group(0)+'}\n'
            code+='''int main(void) {
  const float requests[]={.45f,-.45f,.9f,-.9f,0};
  const float expected[]={.45f,-.45f,.45f,-.45f,0};
  for(unsigned i=0;i<5;++i) {
    MotorControl_SetIq(requests[i]); outer();
    assert(fabsf(foc_iq_ref_A-expected[i])<1e-7f);
    assert(motor_control_mode==3 && !motor_speed_command_rpm && !motor_position_active_hold);
  } return 0;
}'''
            exe=ROOT/f'tests/torque_chain_build/actual450_{slot}.exe'
            p=subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-x','c','-',
                '-o',str(exe)],input=code,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_frozen_math_safety_encoder_pipeline_except_direct_clamp(self):
        for slot in 'ab':
            before=expanded(slot,'Torque350mAFiveSecondDiagnostic')
            after=expanded(slot,'Torque450mAFiveSecondDiagnostic')
            for name in FROZEN+('MotorControl_SetSpeed','MotorControl_SetIq',
                    'FocFp_PushRawSafety','FocOcConfirm_Push','FocFeedbackSafety_Push',
                    'ProtectedLoop_GuardIrqBody','Encoder_ElectricalAngleRad'):
                a,b=function(before,name),function(after,name)
                if name=='MotorControl_SetIq':
                    a=a.replace('-0.35f,','-0.45f,').replace('0.35f);','0.45f);')
                elif name=='FOC_EncoderSpeedUpdate':
                    a=re.sub(r'(ClampFloat\(motor_iq_command_A,\s*)-0\.35f,(\s*)0\.35f\);',
                        r'\g<1>-0.45f,\g<2>0.45f);',a)
                self.assertEqual(a,b,name)
            for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                hashes=[hashlib.sha256(next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes()).hexdigest()
                    for p in ('Torque350mAFiveSecondDiagnostic','Torque450mAFiveSecondDiagnostic')]
                self.assertEqual(*hashes,basename)

    def test_default_off_exclusive_profile_with_existing_baud(self):
        for slot in 'ab':
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(cm,r'option\(FOC_TORQUE450_FIVE_SECOND [^\n]+ OFF\)')
            self.assertIn('MOTOR_DIRECT_IQ_LIMIT_A=0.45f',cm)
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text())
            p=next(p for p in presets['configurePresets'] if p['name']=='Torque450mAFiveSecondDiagnostic')
            self.assertEqual(p['cacheVariables']['FOC_TORQUE_CHAIN_IQ_MA'],'450')
            self.assertEqual(p['cacheVariables']['UART_LOG_BAUD'],'115200')
            for key in ('FOC_ANGLE_CHAIN_DIAG','FOC_SPEED_DYNAMIC_DIAG','FOC_BREAKAWAY_CURRENT_TEST','FOC_TORQUE350_FIVE_SECOND'):
                self.assertEqual(p['cacheVariables'][key],'OFF')

    def test_pinned_image_baseline_and_default_have_no_devices(self):
        self.assertEqual(len(acceptance.image()),222516)
        self.assertEqual(acceptance.old.zero.latest_meta(acceptance.baseline())[2:6],(2,0,0,717))
        p=subprocess.run([sys.executable,str(ROOT/'tools/torque450_five_second_acceptance.py')],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)

    def test_no_power_assertion_no_program_or_unbounded_command(self):
        with patch.object(acceptance.hw,'debug') as debug:
            with self.assertRaises(ValueError): acceptance.stage({},'unused',b'')
            debug.assert_not_called()
        for args in (['--stage-off'],['--execute-powered','unused.json'],['--restore-b-drive-off','unused.json']):
            p=subprocess.run([sys.executable,str(ROOT/'tools/torque450_five_second_acceptance.py'),*args],
                cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        uart=acceptance.TorqueConsole(Mock(),dict(commands=[],start_attempts=1))
        for command in ('START','MOTOR TEST TORQUE450 NEG CONFIRM','MOTOR TEST TORQUE350 CONFIRM'):
            with self.assertRaises(ValueError): uart.torque(command)
        with self.assertRaises(RuntimeError): uart.torque(acceptance.COMMAND)
        uart.port.write.assert_not_called()

    def test_failed_preflight_never_sends_iq_and_stops_captures(self):
        row=dict(steps=[],commands=[]); console=Mock(); port=Mock()
        with patch.object(acceptance,'staged_input',return_value=(ROOT/'tmp/unused.bin',b'capture')), \
             patch.object(acceptance,'open_port',return_value=port), \
             patch.object(acceptance,'TorqueConsole',return_value=console), \
             patch.object(acceptance.hw,'debug'), \
             patch.object(acceptance.old.prior,'wait_health_confirmation',side_effect=RuntimeError('CURRENT_INVALID')), \
             patch.object(acceptance.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'CURRENT_INVALID'):
                acceptance.execute(row,'unused',ROOT/'tmp/unused.json',b'image')
            console.torque.assert_not_called()
            self.assertEqual(console.query.call_args_list[0].args[0],'STOP')
            self.assertEqual(console.query.call_args_list[1].args[0],'ANALOG SAFE')
            capture.assert_called_once()

    def test_baud_drift_rejected_before_device_and_host_uses_same_constant(self):
        acceptance.require_baud('gcc -DUART_LOG_BAUD=115200 -c main.c')
        for cmd in ('gcc -DUART_LOG_BAUD=2000000 -c main.c','gcc -c main.c',
                    'gcc -DUART_LOG_BAUD=115200 -DUART_LOG_BAUD=2000000 -c main.c'):
            with self.assertRaises(ValueError): acceptance.require_baud(cmd)
        fake=Mock(); fake.Serial.return_value=Mock()
        with patch.dict(sys.modules,{'serial':fake}):
            port=acceptance.open_port()
        self.assertEqual(fake.Serial.call_args.kwargs['baudrate'],115200)
        self.assertEqual(port.port,'COM5'); self.assertFalse(port.dtr); self.assertFalse(port.rts)
        port.open.assert_called_once()


if __name__=='__main__': unittest.main()
