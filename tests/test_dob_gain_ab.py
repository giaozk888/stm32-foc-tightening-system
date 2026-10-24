import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import GCC,function
ROOT=Path(__file__).resolve().parents[1]

def expanded(preset):
    build=ROOT/'foc2_app_a/build'/preset
    cmd=next(x['command'] for x in json.loads((build/'compile_commands.json').read_text()) if x['file'].endswith('/Core/Src/main.c'))
    p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),cwd=build,text=True,capture_output=True)
    if p.returncode:raise AssertionError(p.stderr)
    return p.stdout

class GainAbTests(unittest.TestCase):
    def test_native_guard_and_mapping_both_optimizations(self):
        for opt in ['-Os','-O2']:
            exe=ROOT/'tmp'/('dob-gain-ab'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
                              str(ROOT/'tests/dob_gain_ab_host.c'),'-lm','-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS:',p.stdout)
    def test_preprocessed_protections_control_and_trajectory_unchanged(self):
        old,new=(expanded(x) for x in ['DobRealTraceCandidate','DobGainAbCandidate'])
        for name in ['FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
                     'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
                     'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad',
                     'ProtectedLoop_TaskService','FOC_EncoderSpeedUpdate','TighteningTask',
                     'DobNormal_Lifecycle','SpeedFrictionDob_Apply']:
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertNotIn('DobGainAb_Command',old)
        self.assertIn('static float dob_gain_ab=.25f;',new)
        update=function(new,'DobFeedback_Update')
        self.assertIn('dob_gain_ab*estimate',update)
        self.assertNotIn('FOC_DOB_GAIN_AB_DIAG',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

if __name__=='__main__':unittest.main()
