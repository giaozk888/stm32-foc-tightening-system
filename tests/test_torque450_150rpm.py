"""Explicit 150rpm comparison: no devices, speed-limit change only."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque450_150rpm_acceptance as acceptance


class Torque450150Tests(unittest.TestCase):
    def test_real_manual_owner_default_and_150rpm_five_second(self):
        for extra in ([],['-DFOC_TORQUE450_150RPM=1']):
            for opt in ('-Os','-O2'):
                exe=ROOT/('tests/torque_chain_build/torque450rpm'+str(len(extra))+opt+'.exe')
                p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                    '-DFOC_TORQUE450_FIVE_SECOND=1','-DFOC_TORQUE_CHAIN_IQ_MA=450',*extra,
                    '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
                    str(ROOT/'tests/torque_chain_host.c'),'-o',str(exe)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                p=subprocess.run([str(exe)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_control_math_clamps_angles_and_irq_unchanged(self):
        for slot in 'ab':
            a=expanded(slot,'Torque450mAFiveSecondDiagnostic')
            b=expanded(slot,'Torque450mA150rpmFiveSecondDiagnostic')
            for name in FROZEN+('MotorControl_SetIq','MotorControl_SetSpeed',
                    'Encoder_ElectricalAngleRad','FocFp_PushRawSafety',
                    'FocOcConfirm_Push','FocFeedbackSafety_Push','ProtectedLoop_GuardIrqBody'):
                self.assertEqual(function(a,name),function(b,name),name)
            self.assertIn('enum { CL_OVERSPEED_RPM=150U };',b)
            self.assertNotIn('enum { CL_OVERSPEED_RPM=150U };',a)
            self.assertIn('enum { CL_OVERSPEED_RPM=60U };',a)
            for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                hashes=[hashlib.sha256(next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes()).hexdigest()
                    for p in ('Torque450mAFiveSecondDiagnostic','Torque450mA150rpmFiveSecondDiagnostic')]
                self.assertEqual(*hashes,basename)

    def test_default_off_and_restricted_profile(self):
        for slot in 'ab':
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(cm,r'option\(FOC_TORQUE450_150RPM [^\n]+ OFF\)')
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text())
            selected=next(p for p in presets['configurePresets'] if p['name']=='Torque450mA150rpmFiveSecondDiagnostic')
            self.assertEqual(selected['inherits'],'Torque450mAFiveSecondDiagnostic')
            self.assertEqual(selected['cacheVariables'],{'FOC_TORQUE450_150RPM':'ON'})
        p=subprocess.run([GCC,'-std=c11','-DFOC_TORQUE450_150RPM=1',
            '-DFOC_TORQUE_CHAIN_IQ_MA=100','-I',str(ROOT/'firmware_common'),
            '-I',str(ROOT/'foc2_app_a/Core/Inc'),'-fsyntax-only',str(ROOT/'tests/torque_chain_host.c')],
            capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('150rpm comparison requires',p.stderr)

    def test_pinned_150rpm_image_baseline_baud_and_no_device_default(self):
        self.assertEqual(len(acceptance.image()),222532)
        self.assertEqual(acceptance.old.zero.latest_meta(acceptance.baseline())[2:6],(2,0,0,721))
        p=subprocess.run([sys.executable,str(ROOT/'tools/torque450_150rpm_acceptance.py')],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('150rpm trip; no devices',p.stdout)
        with self.assertRaises(ValueError): acceptance.require_baud('gcc -DUART_LOG_BAUD=2000000')

    def test_power_gate_and_no_arbitrary_or_second_start(self):
        with patch.object(acceptance.hw,'debug') as debug:
            with self.assertRaises(ValueError): acceptance.stage({},'unused',b'')
            debug.assert_not_called()
        uart=acceptance.TorqueConsole(Mock(),dict(commands=[],start_attempts=1))
        with self.assertRaises(ValueError): uart.torque('START')
        with self.assertRaises(RuntimeError): uart.torque(acceptance.COMMAND)
        uart.port.write.assert_not_called()

    def test_failed_preflight_keeps_all_protection_and_never_starts(self):
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
            capture.assert_called_once()
        source=(ROOT/'tools/torque450_150rpm_acceptance.py').read_text()
        self.assertIn("RPM_LIMIT='150'",source)
        self.assertIn("TRIP_MA='4000'",source)


if __name__=='__main__': unittest.main()
