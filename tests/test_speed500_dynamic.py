"""SPEED-only owner, unchanged control/protection except the explicit Iq cap."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import Mock,patch
import sys
from test_torque_chain import GCC, FROZEN, function

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import speed500_dynamic_acceptance as acceptance


class Speed500Tests(unittest.TestCase):
    def test_compiled_owner_stop_fault_race_no_fixed_iq(self):
        out=ROOT/'tests/torque_chain_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('speed500'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_SPEED_DYNAMIC_DIAG=1','-I',str(ROOT/'firmware_common'),
                '-I',str(ROOT/'foc2_app_a/Core/Inc'),str(ROOT/'tests/torque_chain_host.c'),
                '-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_preprocessed_control_and_protection_unchanged_except_speed_cap(self):
        for slot in 'ab':
            sources=[]
            for preset in ('Rundown200mADirectLimitTrial','Speed500mADynamicDiagnostic'):
                base=ROOT/f'foc2_app_{slot}/build/{preset}'
                commands=json.loads((base/'compile_commands.json').read_text())
                command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),cwd=base,
                    capture_output=True,text=True,check=True)
                sources.append(p.stdout)
            for name in FROZEN+('MotorControl_SetSpeed','MotorControl_SetIq','FocFp_PushRawSafety',
                    'FocOcConfirm_Push','FocFeedbackSafety_Push','ProtectedLoop_GuardIrqBody',
                    'Encoder_ElectricalAngleRad'):
                old,new=(function(s,name) for s in sources)
                if name=='FOC_EncoderSpeedUpdate':
                    old,count=re.subn(r'(?m)^(\s*)speed_iq_limit_A = 0.40f;',
                        r'\1speed_iq_limit_A = 0.50f;',old)
                    self.assertEqual(count,1)
                self.assertEqual(old,new,name)
            for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                hashes=[hashlib.sha256(next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes()).hexdigest()
                        for p in ('Rundown200mADirectLimitTrial','Speed500mADynamicDiagnostic')]
                self.assertEqual(*hashes,basename)

    def test_explicit_off_default_and_speed_only_task(self):
        for slot in 'ab':
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(cm,r'option\(FOC_SPEED_DYNAMIC_DIAG [^\n]+ OFF\)')
            text=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text()
            self.assertIn('#define MOTOR_DIRECT_IQ_LIMIT_A          0.20f',text)
            task=function(text,'TighteningTask')
            block=task.split('#if defined(FOC_SPEED_DYNAMIC_DIAG)',1)[1].split('#endif',1)[0]
            self.assertIn('continue;',block)
            self.assertNotIn('MotorControl_SetIq',block)
            self.assertIn('vTaskDelay',block)

    def test_exact_images_and_preserved_baseline_files_only(self):
        self.assertEqual(len(acceptance.image()),222028)
        self.assertEqual(acceptance.old.zero.latest_meta(acceptance.current())[2:6],(1,0,0,696))
        p=subprocess.run([sys.executable,str(ROOT/'tools/speed500_dynamic_acceptance.py')],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no device access',p.stdout)

    def test_power_assertion_missing_never_reaches_debugger(self):
        with patch.object(acceptance.hw,'debug') as debug:
            with self.assertRaises(ValueError): acceptance.stage({},'unused',b'')
            debug.assert_not_called()
        for args in (['--restore-b-stage-a'],['--execute-speed','unused.json'],['--verify-compute','unused.json']):
            p=subprocess.run([sys.executable,str(ROOT/'tools/speed500_dynamic_acceptance.py'),*args],
                cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(p.returncode,2,p.stdout+p.stderr)

    def test_bad_preflight_never_sends_speed_and_always_stops(self):
        row=dict(steps=[],commands=[]); console=Mock(); port=Mock()
        with patch.object(acceptance,'staged_input',return_value=(ROOT/'tmp/unused.bin',b'capture')), \
             patch.object(acceptance.old.prior,'open_port',return_value=port), \
             patch.object(acceptance,'SpeedConsole',return_value=console), \
             patch.object(acceptance.hw,'debug'), \
             patch.object(acceptance.old.prior,'wait_health_confirmation',side_effect=RuntimeError('CURRENT_INVALID')), \
             patch.object(acceptance.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'CURRENT_INVALID'):
                acceptance.execute(row,'unused',ROOT/'tmp/unused.json',b'image',motion=True)
            console.speed.assert_not_called()
            self.assertEqual(console.query.call_args_list[0].args[0],'STOP')
            self.assertEqual(console.query.call_args_list[1].args[0],'ANALOG SAFE')
            capture.assert_called_once()
            self.assertNotIn('start_attempts',row)

    def test_only_exact_speed_command_and_no_ack_retry(self):
        row=dict(commands=[],start_attempts=1); uart=acceptance.SpeedConsole(Mock(),row)
        for command in ('START','MOTOR TEST TORQUE POS ZERO CONFIRM','MOTOR TEST SPEED500 999 CONFIRM'):
            with self.assertRaises(ValueError): uart.speed(command)
        with self.assertRaises(RuntimeError): uart.speed(acceptance.COMMAND)
        uart.port.write.assert_not_called()


if __name__=='__main__': unittest.main()
