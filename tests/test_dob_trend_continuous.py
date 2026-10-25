import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_dob_real_trace import expanded
from test_torque_chain import function,GCC

class ContinuousTrendTests(unittest.TestCase):
    def test_real_classifier_continues_for_eight_seconds_and_rings_wrap_without_reset(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-trend-continuous'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/dob_trend_continuous_host.c'),str(ROOT/'firmware_common/dob_trend_continuous.c'),
                str(ROOT/'firmware_common/dob_trend_shadow.c'),'-lm','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(exe),str(ROOT/'tmp'/('dob-trend-continuous'+opt+'.bin'))],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS:',p.stdout)

    def test_all_original_control_and_protection_owners_identical(self):
        before,after=(expanded(p) for p in ('DobTrendShadowTrip500Candidate','DobTrendContinuousTrip500Candidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready',
                     'LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq',
                     'MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService',
                     'FOC_EncoderSpeedUpdate','TighteningTask','IntentPort_Config'):
            self.assertEqual(function(before,name),function(after,name),name)
        flush=function(after,'OuterObservation_Flush')
        self.assertNotIn('Mechanical_Observe(',flush)
        self.assertLess(flush.index('MechanicalDobMonitor_Observe'),flush.index('DobTrendContinuous_Observe'))
        self.assertIn('CL_OVERSPEED_RPM=500U',after)

    def test_pure_observer_and_old_version_kept_for_frozen_receipts(self):
        source=(ROOT/'firmware_common/dob_trend_continuous.c').read_text()
        for token in ('TIM1','HAL_','MotorControl_','UART_','malloc','DobFeedback','MechanicalDob','TightenParams_'):
            self.assertNotIn(token,source)
        self.assertNotIn('h->post_count',source)
        self.assertIn('dob_trend_shadow.flags&DTS_DONE', (ROOT/'firmware_common/dob_trend_shadow.c').read_text())

if __name__=='__main__':unittest.main()
