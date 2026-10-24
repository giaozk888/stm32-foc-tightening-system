import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest
from test_torque_chain import ROOT,GCC,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import ka_sync_report as report


class KaSyncTests(unittest.TestCase):
    def test_actual_c_snapshot_quantization_wrap_bounded_capture_and_decode(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/('tmp/ka-sync'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/ka_sync_host.c'),
                str(ROOT/'firmware_common/ka_sync_diagnostic.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            lines=p.stdout.splitlines();self.assertEqual(len(lines),2)
            data=bytes.fromhex(lines[0]);r=report.decode_bytes(data)
            self.assertTrue(r['complete_short_window']);self.assertTrue(r['all_observations_valid'],r['problems'])
            self.assertEqual(r['span_us'],63000)
            self.assertEqual(r['current_minus_encoder_time_us'],dict(min=30,max=30,mean=30))
            self.assertIsNone(r['points'][0]['iq_interpolated_at_encoder_a'])
            self.assertAlmostEqual(r['points'][1]['iq_interpolated_at_encoder_a'],.15)
            self.assertIsNone(r['ka_identified'])
            wrapped=report.decode_bytes(bytes.fromhex(lines[1]))
            self.assertTrue(wrapped['all_observations_valid'],wrapped['problems'])
            self.assertGreater(wrapped['points'][0]['encoder_us'],wrapped['points'][-1]['encoder_us'])
            self.assertGreater(wrapped['points'][0]['current_adc_seq'],wrapped['points'][-1]['current_adc_seq'])
            bad=bytearray(data);bad[7]=4
            self.assertFalse(report.decode_bytes(bad)['all_observations_valid'])
            bad=bytearray(data);struct.pack_into('<I',bad,1156,65)
            with self.assertRaises(ValueError):report.decode_bytes(bad)

    def test_compiled_diagnostic_only_no_controller_or_irq_policy_change(self):
        old=expanded('a','BemfFittedFluxCandidate');new=expanded('a','KaSynchronizedDiagnostic')
        new=new.replace('0.0000000f','0.0001875f')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','FOC_ResetController',
            'MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_PwmEntry',
            'ProtectedLoop_SetDuty','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'PowerStage_Enable','PowerStage_Disable','TighteningTask','SpeedPiAntiWindup_Apply'):
            a=function(old,name);b=function(new,name)
            b=re.sub(r'uint32_t sync_begin=[\s\S]*?ka_sync_diagnostic.publish_cycles_max=sync_cycles;','',b)
            b=re.sub(r'KaSyncCurrent sync_current;[\s\S]*?&sync_current,sync_valid\);','',b)
            self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b),name)
        irq=function(new,'FOC_CurrentLoopStep')
        self.assertIn('KaSync_Publish(',irq);self.assertNotIn('printf',function(new,'KaSync_Publish'))
        self.assertNotIn('__disable_irq',function(new,'KaSync_TryRead'))
        self.assertNotIn('SpeedFriction_Log(',function(new,'SpeedAccelFf_Monitor'))

    def test_default_builds_and_old_capture_binaries_unchanged(self):
        expected={
            'foc2_app_a/build/BemfFittedFluxCandidate/foc2.bin':'6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f',
            'foc2_app_a/build/KaIdentificationDiagnostic/foc2.bin':'cd9f970c4ddfb3ce8ddb9f2e13e1046441d5644bb05df01e493f726d570fb8be',
            'foc2_app_b/build/FrictionBUnchanged/foc2.bin':'7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366'}
        for name,sha in expected.items():self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),sha)
        text=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(text,r'option\(FOC_KA_SYNC_DIAG [^\n]+ OFF\)')
        self.assertNotIn('FOC_KA_SYNC_DIAG',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_decoder_refuses_old_abi_and_has_no_device_or_parameter_writes(self):
        with self.assertRaises(ValueError):report.decode_bytes(bytes(1032))
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_sync_report.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0);self.assertIn('FILES ONLY',p.stdout)
        self.assertNotIn('import serial',(ROOT/'tools/ka_sync_report.py').read_text())


if __name__=='__main__':unittest.main()
