import json
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,function
from test_dob_real_trace import expanded
ROOT=Path(__file__).resolve().parents[1]
class CandidateTests(unittest.TestCase):
    def test_board_classifier_matches_tested_offline75_all_scalar_states(self):
        files=[]
        for candidate in (False,True):
            include=ROOT/'firmware_common' if candidate else ROOT/'simulation/dob_simulink/window_scan_work/generated'
            stem=ROOT/'tmp'/('window75-deploy' if candidate else 'window75-simulink-ref')
            flags=['-DFOC_DOB_TREND_WINDOW75=1'] if candidate else [
                '-DDOB_WINDOW_POINTS=75U','-DDOB_WINDOW_MIN_GOOD=45U','-DDOB_WINDOW_MIN_SPAN_US=45000U']
            for opt in ('-Os','-O2'):
                exe=str(stem)+opt+'.exe';out=str(stem)+opt+'.bin'
                p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-DDOB_WINDOW_SCALAR_TRACE=1',*flags,
                    '-I',str(include),str(ROOT/'tests/dob_window_scan_host.c'),str(include/'dob_trend_shadow.c'),
                    '-lm','-o',exe],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                p=subprocess.run([exe,out],capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                files.append(Path(out).read_bytes())
        for content in files[1:]:self.assertEqual(files[0],content)
    def test_control_safety_and_observer_math_unchanged(self):
        old,new=(expanded(p) for p in ('DobWarmup3Candidate','DobWindow75Warmup3Candidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready',
            'LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq',
            'MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService','TighteningTask',
            'OuterObservation_Flush','IntentPort_Config','DobFeedback_Update','SpeedFrictionDob_Apply','FOC_EncoderSpeedUpdate'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertIn('WINDOW_MS=75 MIN_GOOD=45 MIN_SPAN_US=45000',new)
        self.assertIn('CL_OVERSPEED_RPM=500U',new)
    def test_no_default_or_B_profile_changes(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        self.assertEqual([p['name'] for p in presets if p.get('cacheVariables',{}).get('FOC_DOB_TREND_WINDOW75')=='ON'],['DobWindow75Warmup3Candidate'])
        self.assertNotIn('FOC_DOB_TREND_WINDOW75',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
if __name__=='__main__':unittest.main()
