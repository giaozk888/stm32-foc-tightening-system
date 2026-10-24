import hashlib
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]

class GainHalfTests(unittest.TestCase):
    def test_actual_half_gain_preserves_all_bounds_and_lifecycle(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-feedback-gainhalf'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-DDOB_FB_GAIN=0.5f',
                '-DEXPECTED_DOB_FB_GAIN=0.5f','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/dob_feedback_gain1_host.c'),str(ROOT/'firmware_common/speed_friction_compensation.c'),
                str(ROOT/'firmware_common/speed_accel_feedforward.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS: gain0.5',p.stdout)

    def test_compiled_half_gain_only_no_control_parameter_or_previous_image_change(self):
        old,new=(expanded('a',p) for p in ('MechanicalDobFeedbackGain1Candidate','MechanicalDobFeedbackGainHalfCandidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
            'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService',
            'FOC_EncoderSpeedUpdate'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertIn('float raw=0.5f*estimate',new)
        self.assertIn('float cap=fminf(.025f,.05f*iq_limit)',new)
        self.assertNotIn('FOC_DOB_FB_GAIN_HALF',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        b=ROOT/'foc2_app_a/build/MechanicalDobFeedbackGain1Candidate/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
                         'cfb4a3c6b26add1533b7d50aeadd9f83cbdbc2bf684351b195468186c592b131')

if __name__=='__main__':unittest.main()
