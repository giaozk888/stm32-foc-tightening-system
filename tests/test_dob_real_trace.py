import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_torque_chain import GCC,function

def expanded(preset):
    build=ROOT/'foc2_app_a/build'/preset
    cmd=next(c['command'] for c in json.loads((build/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
    p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),cwd=build,text=True,capture_output=True)
    if p.returncode:raise AssertionError(p.stderr)
    return p.stdout

class RawTraceTests(unittest.TestCase):
    def test_native_fixed_window_including_spikes_gaps_and_invalid_data(self):
        for opt in ['-Os','-O2']:
            exe=ROOT/'tmp'/('dob-real-trace'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/dob_real_trace_host.c'),str(ROOT/'firmware_common/dob_real_trace.c'),'-lm','-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def test_critical_foc_irq_owners_identical_to_existing_contact20_candidate(self):
        old,new=(expanded(p) for p in ['TighteningDob025Contact20Observe10Candidate','DobRealTraceCandidate'])
        for name in ['FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
            'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService',
            'FOC_EncoderSpeedUpdate','TighteningTask']:
            self.assertEqual(function(old,name),function(new,name),name)
        flush=function(new,'OuterObservation_Flush')
        self.assertLess(flush.index('MechanicalDobMonitor_Observe'),flush.index('DobRealTrace_Observe'))
        self.assertIn('static DobFeedbackCandidate dob_feedback;',new)
        self.assertIn('static DobFeedbackCandidate dob_feedback={.enabled=1U};',old)
    def test_recorder_has_no_actuation_storage_uart_or_allocation(self):
        source=(ROOT/'firmware_common/dob_real_trace.c').read_text()
        for token in ['HAL_','UART_','PWM_','MotorControl_','malloc','TightenParams_']:
            self.assertNotIn(token,source)

if __name__=='__main__':unittest.main()
