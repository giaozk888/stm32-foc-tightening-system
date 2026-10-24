import hashlib
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]

class Gain015Tests(unittest.TestCase):
    def test_actual_gain015_preserves_bounds_and_lifecycle(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-feedback-gain015'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-DDOB_FB_GAIN=0.15f',
                '-DEXPECTED_DOB_FB_GAIN=0.15f','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/dob_feedback_gain1_host.c'),str(ROOT/'firmware_common/speed_friction_compensation.c'),
                str(ROOT/'firmware_common/speed_accel_feedforward.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS: gain0.15',p.stdout)

    def test_compiled_only_gain_changed_and_previous_image_frozen(self):
        old,new=(expanded('a',p) for p in ('MechanicalDobFeedbackGainHalfCandidate','MechanicalDobFeedbackGain015Candidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
            'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService',
            'FOC_EncoderSpeedUpdate'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertIn('float raw=0.15f*estimate',new)
        self.assertIn('float cap=fminf(.025f,.05f*iq_limit)',new)
        self.assertNotIn('FOC_DOB_FB_GAIN_015',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        b=ROOT/'foc2_app_a/build/MechanicalDobFeedbackGainHalfCandidate/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
                         '3508081b2835eb4668aba861cfdc3abc3061948c37bd01be405d42e8eb74e474')

if __name__=='__main__':unittest.main()
