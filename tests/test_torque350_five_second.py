"""Fixed +350mA five-second diagnostic: compiled owner and actual clamps."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import Mock,patch
import sys
from test_torque_chain import GCC,FROZEN,function

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque350_five_second_acceptance as acceptance


def expanded(slot,preset):
    base=ROOT/f'foc2_app_{slot}/build/{preset}'
    commands=json.loads((base/'compile_commands.json').read_text())
    command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
    p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),cwd=base,
        capture_output=True,text=True,check=True)
    return p.stdout


class Torque350Tests(unittest.TestCase):
    def test_actual_owner_exact_positive_only_five_second_stop_fault_races(self):
        out=ROOT/'tests/torque_chain_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('torque350'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_TORQUE350_FIVE_SECOND=1','-DFOC_TORQUE_CHAIN_IQ_MA=350',
                '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
                str(ROOT/'tests/torque_chain_host.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_actual_setter_and_outer_apply_350_not_old_200(self):
        for slot in 'ab':
            source=expanded(slot,'Torque350mAFiveSecondDiagnostic')
            setter=function(source,'MotorControl_SetIq')
            self.assertIn('-0.35f',setter)
            self.assertIn('0.35f',setter)
            outer=function(source,'FOC_EncoderSpeedUpdate')
            assign=re.search(r'foc_iq_ref_A\s*=\s*ClampFloat\(motor_iq_command_A,\s*-0.35f,\s*0.35f\);',outer).group(0)
            code='''#include <assert.h>
#include <math.h>
#define MOTOR_MODE_IQ 3
static unsigned motor_control_mode,motor_position_active_hold,invalidations;
static float motor_iq_command_A,motor_speed_command_rpm,foc_iq_ref_A;
static void ProtectedLoop_PwmInvalidate(void) {++invalidations;}
'''
            code+='static float '+function(source,'ClampFloat')+'\n'
            code+='static void '+setter+'\nstatic void outer(void) {'+assign+'}\n'
            code+='''int main(void) {
  const float requests[]={.35f,-.35f,.5f,-.5f,0};
  const float expect[]={.35f,-.35f,.35f,-.35f,0};
  for(unsigned i=0;i<5;++i) {
    motor_control_mode=0; motor_speed_command_rpm=20; motor_position_active_hold=1;
    MotorControl_SetIq(requests[i]); outer();
    assert(motor_control_mode==3 && !motor_speed_command_rpm && !motor_position_active_hold);
    assert(fabsf(foc_iq_ref_A-expect[i])<1e-7f);
  }
  assert(invalidations==5); return 0;
}'''
            exe=ROOT/f'tests/torque_chain_build/actual350_{slot}.exe'
            p=subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-x','c','-',
                '-o',str(exe)],input=code,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_frozen_math_safety_irq_except_explicit_direct_clamp(self):
        for slot in 'ab':
            before=expanded(slot,'Rundown200mADirectLimitTrial')
            after=expanded(slot,'Torque350mAFiveSecondDiagnostic')
            for name in FROZEN+('MotorControl_SetSpeed','MotorControl_SetIq',
                'FocFp_PushRawSafety','FocOcConfirm_Push','FocFeedbackSafety_Push',
                'ProtectedLoop_GuardIrqBody','Encoder_ElectricalAngleRad'):
                old,new=function(before,name),function(after,name)
                if name in ('MotorControl_SetIq','FOC_EncoderSpeedUpdate'):
                    old=old.replace('-0.20f,','-0.35f,').replace('0.20f);','0.35f);')
                self.assertEqual(old,new,name)
            for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                hashes=[hashlib.sha256(next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes()).hexdigest()
                    for p in ('Rundown200mADirectLimitTrial','Torque350mAFiveSecondDiagnostic')]
                self.assertEqual(*hashes,basename)

    def test_default_off_and_exclusive_profile(self):
        for slot in 'ab':
            text=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(text,r'option\(FOC_TORQUE350_FIVE_SECOND [^\n]+ OFF\)')
            self.assertIn('MOTOR_DIRECT_IQ_LIMIT_A=0.35f',text)
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text())
            p=next(p for p in presets['configurePresets'] if p['name']=='Torque350mAFiveSecondDiagnostic')
            self.assertEqual(p['cacheVariables']['FOC_TORQUE_CHAIN_IQ_MA'],'350')
            self.assertEqual(p['cacheVariables']['FOC_SPEED_DYNAMIC_DIAG'],'OFF')

    def test_exact_baseline_image_and_default_no_devices(self):
        self.assertEqual(len(acceptance.image()),222516)
        self.assertEqual(acceptance.old.zero.latest_meta(acceptance.baseline())[2:6],(2,0,0,701))
        p=subprocess.run([sys.executable,str(ROOT/'tools/torque350_five_second_acceptance.py')],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)

    def test_missing_power_assertion_never_programs(self):
        with patch.object(acceptance.hw,'debug') as debug:
            with self.assertRaises(ValueError): acceptance.stage({},'unused',b'')
            debug.assert_not_called()
        for args in (['--stage-off'],['--execute-powered','unused.json'],['--restore-b-drive-off','unused.json']):
            p=subprocess.run([sys.executable,str(ROOT/'tools/torque350_five_second_acceptance.py'),*args],
                cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(p.returncode,2,p.stdout+p.stderr)

    def test_current_invalid_preflight_never_sends_iq_and_captures(self):
        row=dict(steps=[],commands=[]); console=Mock(); port=Mock()
        with patch.object(acceptance,'staged_input',return_value=(ROOT/'tmp/unused.bin',b'capture')), \
             patch.object(acceptance.old.prior,'open_port',return_value=port), \
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

    def test_no_arbitrary_command_or_ack_retry(self):
        uart=acceptance.TorqueConsole(Mock(),dict(commands=[],start_attempts=1))
        for command in ('START','MOTOR TEST TORQUE350 NEG CONFIRM','MOTOR TEST BREAKAWAY POS 350 CONFIRM'):
            with self.assertRaises(ValueError): uart.torque(command)
        with self.assertRaises(RuntimeError): uart.torque(acceptance.COMMAND)
        uart.port.write.assert_not_called()

    def test_retry_inspection_is_exact_and_has_no_reset_flash_or_start(self):
        data=acceptance.image(); before=acceptance.retry_baseline(data)
        self.assertEqual(acceptance.old.zero.latest_meta(before)[2:6],(2,0,0,705))
        with patch.object(acceptance.hw,'debug') as debug:
            with self.assertRaises(ValueError): acceptance.inspect_retry_off({},'unused',data)
            debug.assert_not_called()
        source=(ROOT/'tools/torque350_five_second_acceptance.py').read_text()
        body=source.split('def inspect_retry_off(',1)[1].split('\n\nclass ',1)[0]
        self.assertNotIn("'reset",body)
        self.assertNotIn('flash write_image',body)
        self.assertIn('verify_image',body)
        self.assertIn('full_compare_commands',body)


if __name__=='__main__': unittest.main()
