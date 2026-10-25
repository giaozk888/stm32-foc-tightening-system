"""Files-only regressions for the A-only observer; no device imports."""
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_dob_real_trace import expanded
from test_torque_chain import function,GCC

class TrendShadowTests(unittest.TestCase):
    def test_host_matches_selected_simulink_classifier(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-trend-shadow'+opt+'.exe')
            cmd=[GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
                 '-I',str(ROOT/'simulation/dob_simulink/native'),str(ROOT/'tests/dob_trend_shadow_host.c'),
                 str(ROOT/'firmware_common/dob_trend_shadow.c'),str(ROOT/'simulation/dob_simulink/native/load_features.c'),
                 '-lm','-o',str(exe)]
            p=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS:',p.stdout)

    def test_original_control_and_protection_owners_unchanged(self):
        old,new=(expanded(p) for p in ('DobGainAbCandidate','DobTrendShadowCandidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
                     'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
                     'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad',
                     'ProtectedLoop_TaskService','FOC_EncoderSpeedUpdate','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        flush=function(new,'OuterObservation_Flush')
        self.assertNotIn('Mechanical_Observe(',flush)
        self.assertLess(flush.index('MechanicalDobMonitor_Observe'),flush.index('DobTrendShadow_Observe'))
        self.assertIn('static DobFeedbackCandidate dob_feedback;',new)

    def test_no_actuation_or_original_observer_mutation(self):
        source=(ROOT/'firmware_common/dob_trend_shadow.c').read_text()
        for token in ('HAL_','TIM1','UART_','PWM_','MotorControl_','malloc','TightenParams_',
                      'MechanicalDob','DobFeedback','dob_current_admission','abs_id_lpf'):
            self.assertNotIn(token,source)

if __name__=='__main__':unittest.main()
