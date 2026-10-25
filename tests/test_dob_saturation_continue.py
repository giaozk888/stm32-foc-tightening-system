import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_dob_normal_control import FLAGS
from test_torque_chain import function,GCC
from test_dob_real_trace import expanded

class SaturationContinueTests(unittest.TestCase):
    def test_actual_estimator_saturation_feedback_and_unchanged_fault_admission(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-saturation-continue'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-DFOC_DOB_CONTACT20_OBSERVE10=1','-DFOC_DOB_SATURATION_CONTINUE=1',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_saturation_continue_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),'-lm','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS:',p.stdout)

    def test_foc_protection_fsm_and_pi_math_unchanged(self):
        old,new=(expanded(p) for p in ('DobTrendContinuousTrip500Candidate','DobSaturationContinuousCandidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready',
            'LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq',
            'MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService','TighteningTask',
            'OuterObservation_Flush','IntentPort_Config','DobFeedback_Update','SpeedFrictionDob_Apply'):
            self.assertEqual(function(old,name),function(new,name),name)
        before=function(old,'FOC_EncoderSpeedUpdate');after=function(new,'FOC_EncoderSpeedUpdate')
        after=re.sub(r'if\(mechanical_dob_monitor.current.status&DOB_MONITOR_SATURATED\)\s*\+\+dob_saturation_audit.feedback_blocks;','',after)
        after=after.replace('&&!(mechanical_dob_monitor.current.status&DOB_MONITOR_SATURATED)','')
        self.assertEqual(re.sub(r'\s+','',before),re.sub(r'\s+','',after))
        self.assertIn('CL_OVERSPEED_RPM=500U',new)

    def test_macro_is_opt_in_and_not_in_B_or_normal_default(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        self.assertEqual([p['name'] for p in presets if p.get('cacheVariables',{}).get('FOC_DOB_SATURATION_CONTINUE')=='ON'],['DobSaturationContinuousCandidate'])
        self.assertNotIn('FOC_DOB_SATURATION_CONTINUE',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

if __name__=='__main__':unittest.main()
