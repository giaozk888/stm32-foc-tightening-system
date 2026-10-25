import json
from pathlib import Path
import re
import subprocess
import struct
import sys
import unittest
from unittest.mock import patch
from test_dob_normal_control import FLAGS
from test_torque_chain import GCC,function
from test_dob_real_trace import expanded
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_recovery_decode as decoder
class RecoveryTests(unittest.TestCase):
    def test_actual_monitor_recovery_timing_and_no_classifier_changes(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-recovery'+opt+'.exe');trace=exe.with_suffix('.bin')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-DFOC_DOB_CONTACT20_OBSERVE10=1','-DFOC_DOB_SATURATION_CONTINUE=1','-DFOC_DOB_TREND_CONTINUOUS=1',
                '-DFOC_DOB_TREND_WINDOW75=1','-DFOC_DOB_WARMUP_AB=1','-DDOB_WARMUP_DEFAULT_TAU=3U',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_recovery_timing_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),str(ROOT/'firmware_common/dob_trend_shadow.c'),
                str(ROOT/'firmware_common/dob_recovery_timing.c'),'-lm','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(exe),str(trace)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS:',p.stdout)
    def test_real_control_and_gates_identical_one_passive_after_ack_hook(self):
        old,new=(expanded(p) for p in ('DobWindow75Warmup3Candidate','DobRecoveryBreakdownCandidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready',
            'LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','ProtectedLoop_TaskService','TighteningTask','IntentPort_Config',
            'DobFeedback_Update','SpeedFrictionDob_Apply','FOC_EncoderSpeedUpdate'):
            self.assertEqual(function(old,name),function(new,name),name)
        before=function(old,'OuterObservation_Flush');after=function(new,'OuterObservation_Flush')
        self.assertLess(after.index('DobTrendContinuous_Observe'),after.index('DobRecovery_Observe'))
        after=re.sub(r'if\(dob_trend_continuous_arena\)\s*DobRecovery_Observe\([^;]+;', '',after)
        self.assertEqual(re.sub(r'\s+','',before),re.sub(r'\s+','',after))
    def test_opt_in_only_and_no_actuation_in_diagnostic(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        self.assertEqual([p['name'] for p in presets if p.get('cacheVariables',{}).get('FOC_DOB_RECOVERY_TIMING')=='ON'],['DobRecoveryBreakdownCandidate'])
        self.assertNotIn('FOC_DOB_RECOVERY_TIMING',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        source=(ROOT/'firmware_common/dob_recovery_timing.c').read_text()
        for token in ('HAL_','TIM1','PWM_','MotorControl_','TightenParams_','malloc','UART_','MechanicalDob_Reset','DobAdmit_'):
            self.assertNotIn(token,source)
    def test_saved_trace_decoder_closure_and_synthetic_scope(self):
        result=decoder.load(fixture=ROOT/'tmp/dob-recovery-Os.bin')
        self.assertEqual(result['source_kind'],'synthetic_native_fixture')
        self.assertEqual(len(result['records']),2)
        r=result['records'][1]
        self.assertEqual(r['qualify_us'],0);self.assertEqual(r['warm_us'],239000)
        self.assertEqual(r['wall_us'],417000);self.assertEqual(r['partition_sum_us'],r['wall_us'])
        self.assertEqual(r['lead_in_us'],19000)
        self.assertTrue(r['starts_at_classifier_reset'] and r['timing_qualified'])
        data=bytearray((ROOT/'tmp/dob-recovery-Os.bin').read_bytes())
        struct.pack_into('<I',data,68+48+8,999) # Corrupt the second record's low-speed partition.
        with self.assertRaisesRegex(ValueError,'partition'):decoder.decode(data[:68],data[68:])
    def test_scattered_borrowed_bytes_decode_and_legacy_image_not_supported(self):
        data=(ROOT/'tmp/dob-recovery-Os.bin').read_bytes();ram=bytearray(8192);ram[:68]=data[:68]
        ram[256+300:256+400]=data[68:168];ram[256+700:256+800]=data[168:268]
        path=ROOT/'tmp/dob-recovery-decoder-ram.bin';path.write_bytes(ram)
        elf=ROOT/'foc2_app_a/build/DobRecoveryBreakdownCandidate/foc2.elf'
        with patch.object(decoder,'symbols',return_value=dict(dob_recovery_timing=(0x20000000,68),mechanical_capture=(0x20000100,4712))):
            result=decoder.load(ram=path,elf=elf)
        self.assertEqual(result['records'][1]['wall_us'],417000)
        old=ROOT/'foc2_app_a/build/DobWindow75Warmup3Candidate/foc2.elf'
        with self.assertRaises(KeyError):decoder.load(ram=path,elf=old)
if __name__=='__main__':unittest.main()
