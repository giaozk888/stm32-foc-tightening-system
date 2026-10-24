import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]

class GainOneTests(unittest.TestCase):
    def test_production_unit_gain_preserves_caps_slew_lifecycle_and_aw(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-feedback-gain1'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-DDOB_FB_GAIN=1.0f',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_feedback_gain1_host.c'),
                str(ROOT/'firmware_common/speed_friction_compensation.c'),
                str(ROOT/'firmware_common/speed_accel_feedforward.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS: gain1',p.stdout)

    def test_actual_compiled_gain_and_frozen_safety_and_previous_images(self):
        old,new=(expanded('a',p) for p in ('MechanicalDobFeedbackCandidate','MechanicalDobFeedbackGain1Candidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
            'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService',
            'FOC_EncoderSpeedUpdate'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertIn('float raw=1.0f*estimate',new)
        self.assertIn('float cap=fminf(.025f,.05f*iq_limit)',new)
        self.assertNotIn('FOC_DOB_FB_GAIN_ONE',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        b=ROOT/'foc2_app_a/build/MechanicalDobFeedbackCandidate/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
                         '9d4dae1bc55fb85fa5b821651ee0886e670644ad00ef3c77cd2923b3ce075aad')

if __name__=='__main__':unittest.main()
