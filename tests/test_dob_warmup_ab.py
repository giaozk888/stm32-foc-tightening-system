import json
from pathlib import Path
import subprocess
import unittest
from test_dob_normal_control import FLAGS
from test_torque_chain import GCC,function
from test_dob_real_trace import expanded
ROOT=Path(__file__).resolve().parents[1]
class WarmupTests(unittest.TestCase):
    def test_native_actual_gate_same_estimator_and_command_guards(self):
        for opt,default in (('-Os',5),('-O2',5),('-Os',3),('-O2',3)):
            exe=ROOT/'tmp'/('dob-warmup'+opt+str(default)+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-DFOC_DOB_WARMUP_AB=1','-DDOB_WARMUP_DEFAULT_TAU='+str(default)+'U',
                '-DFOC_DOB_CONTACT20_OBSERVE10=1','-DFOC_DOB_SATURATION_CONTINUE=1',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_warmup_ab_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),'-lm','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS:',p.stdout)
    def test_compiled_control_and_protections_identical(self):
        old,new=(expanded(p) for p in ('DobSaturationContinuousCandidate','DobWarmupAbCandidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready',
            'LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq',
            'MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService','TighteningTask',
            'OuterObservation_Flush','IntentPort_Config','DobFeedback_Update','SpeedFrictionDob_Apply','FOC_EncoderSpeedUpdate'):
            self.assertEqual(function(old,name),function(new,name),name)
    def test_opt_in_only(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        self.assertEqual([p['name'] for p in presets if p.get('cacheVariables',{}).get('FOC_DOB_WARMUP_AB')=='ON'],['DobWarmupAbCandidate'])
        self.assertNotIn('FOC_DOB_WARMUP_AB',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
    def test_three_tau_candidate_preserves_comparison_image_and_control(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        selected=next(p for p in presets if p['name']=='DobWarmup3Candidate')
        self.assertEqual(selected['cacheVariables'],{'FOC_DOB_WARMUP_DEFAULT_TAU':'3'})
        old,new=(expanded(p) for p in ('DobWarmupAbCandidate','DobWarmup3Candidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
                     'FOC_EncoderSpeedUpdate','DobFeedback_Update','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertIn('(unsigned long)3U',function(new,'DobWarmupAb_Command'))
        self.assertIn('(unsigned long)5U',function(old,'DobWarmupAb_Command'))
if __name__=='__main__':unittest.main()
