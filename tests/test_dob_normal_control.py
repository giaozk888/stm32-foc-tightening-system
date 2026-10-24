import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
from test_dob_id_pre_lpf_200 import FLAGS as OLD_FLAGS
ROOT=Path(__file__).resolve().parents[1]
FLAGS=[f for f in OLD_FLAGS if f!='-DFOC_DOB_ID_TRACE=1']+[
    '-DFOC_DOB_NORMAL_CONTROL=1','-DFOC_DOB_FEEDBACK_CANDIDATE=1','-DDOB_FB_GAIN=0.25f']

class NormalDobTests(unittest.TestCase):
    def test_real_lifecycle_warmup_stop_fault_mode_reentry_spike_and_persistent_id(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-normal'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_normal_control_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS: normal DOB',p.stdout)

    def test_compiled_normal_start_owner_limits_guards_and_default_enabled(self):
        normal=expanded('a','TighteningDob025')
        prior=expanded('a','MechanicalDobFeedbackCandidate')
        base=expanded('a','TighteningBemfHalfCandidate')
        self.assertIn('static DobFeedbackCandidate dob_feedback={.enabled=1U}',normal)
        self.assertIn('float raw=0.25f*estimate',normal)
        self.assertIn('DobNormal_Lifecycle',function(normal,'ProtectedLoop_TaskService'))
        self.assertNotIn('friction_calibration',normal)
        self.assertNotIn('FrictionCalibration_Command',normal)
        self.assertIn('IntentPort_Config',normal)
        self.assertIn('recipe_state.params.rundown_rpm',function(normal,'LatestOriginal_RecipeReady'))
        self.assertIn('MechanicalDob_Command',function(normal,'ProtectedLoop_Command'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','PowerStage_Enable','PowerStage_Disable',
                     'MotorControl_SetIq','Encoder_ElectricalAngleRad'):
            self.assertEqual(function(prior,name),function(normal,name),name)
        for name in ('MotorControl_SetSpeed','ProtectedLoop_GuardIrqBody','LatestOriginal_Admit','ClSession_Queue','ClSession_Start'):
            self.assertEqual(function(base,name),function(normal,name),name)
        for text in ('CL_OVERSPEED_RPM=300U','CL_MAX_US=12000000U'):
            self.assertIn(text,normal)
        speed=function(normal,'FOC_EncoderSpeedUpdate')
        self.assertIn('600.0f',speed) # Original normal plausibility envelope, not diagnostic1000rpm.
        self.assertIn('SpeedFrictionDob_Apply',speed)
        self.assertLess(speed.index('SpeedFrictionDob_Apply'),speed.index('speed_integrator_A=aff.integral_a'))
        self.assertIn('foc_iq_ref_A = iq_cmd;',speed)

    def test_conflicting_gain_or_diagnostic_owner_rejected(self):
        for name,flag in (('gain','FOC_DOB_FB_GAIN_HALF'),('motion','FOC_MECHANICAL_HIGH_SPEED_DIAG'),
                          ('owner','FOC_FRICTION_CALIBRATION_DIAG')):
            p=subprocess.run(['cmake','--preset','TighteningDob025','-B',str(ROOT/'tmp'/('dob-normal-bad-'+name)),
                '-D'+flag+'=ON'],cwd=ROOT/'foc2_app_a',text=True,capture_output=True)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('Normal DOB requires',p.stdout+p.stderr)

    def test_previous_frozen_images_and_b_sources_not_promoted(self):
        for preset,sha in (
            ('MechanicalDobFeedbackCandidate','9d4dae1bc55fb85fa5b821651ee0886e670644ad00ef3c77cd2923b3ce075aad'),
            ('MechanicalDobFeedbackGainHalfCandidate','3508081b2835eb4668aba861cfdc3abc3061948c37bd01be405d42e8eb74e474'),
            ('MechanicalDobFeedbackGain015Candidate','ee8481cdae09e92b4c4417a542be2f08580013a0f88e0aef4cd6acdae06f1fee')):
            self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build'/preset/'foc2.bin').read_bytes()).hexdigest(),sha)
        self.assertNotIn('FOC_DOB_NORMAL_CONTROL',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        b=ROOT/'foc2_app_b/build/MechanicalReviewB/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
                         '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')

if __name__=='__main__':unittest.main()
