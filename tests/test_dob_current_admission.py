from pathlib import Path
import json
import re
import subprocess
import sys
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_id_trace_report as report


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=[]
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-current-admission'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_DOB_ID_TRACE=1','-DFOC_DOB_SPIKE_ADMISSION=1','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/dob_current_admission_host.c'),str(ROOT/'firmware_common/dob_id_trace.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),'-o',str(exe)],text=True,capture_output=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            p=subprocess.run([str(exe),'binary'],capture_output=True)
            if p.returncode:raise AssertionError(p.stderr)
            cls.raw.append(p.stdout)

    def test_actual_c_two_optimizations_paired_filter_freeze_transition_and_exit(self):
        self.assertEqual(len(self.raw),2)

    def test_v2_trace_preserves_raw_pair_actual_filter_reset_warmup_and_decisions(self):
        for raw in self.raw:
            d=report.decode_bytes(raw[:96],raw[96:]);rows=d['rows']
            self.assertTrue(d['complete'] and d['triggered']);self.assertEqual(len(rows),192)
            spike,ret,norm=rows[32:35]
            self.assertEqual(spike['admission_name'],'SUSPECT')
            self.assertEqual(ret['admission_name'],'SPIKE_RETURN')
            self.assertEqual(norm['admission_name'],'NORMAL')
            self.assertAlmostEqual(spike['id_meas_a'],-.561689,places=6)
            self.assertAlmostEqual(spike['iq_meas_a'],.22,places=6)
            self.assertFalse(spike['reset'] or spike['valid'] or ret['reset'] or ret['valid'])
            self.assertTrue(norm['valid']);self.assertEqual(spike['warmup_s'],ret['warmup_s'])
            self.assertEqual(d['checks']['hold_lpf_change_a'],0)
            self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)
            self.assertLess(d['checks']['max_warmup_increment_error_s'],1e-7)

    def test_existing_v1_board_record_remains_decodable(self):
        r=Path('tmp/mechanical-ident-run-1792721083841614700.json')
        d=report.decode(ROOT/r,ROOT/'foc2_app_a/build/MechanicalDobIdTraceCandidate/foc2.elf')
        self.assertEqual(d['meta']['abi'],1);self.assertTrue(d['board_verified'])
        self.assertEqual(len(d['rows']),288)

    def test_control_protection_interrupts_and_b_frozen(self):
        old=expanded('a','MechanicalDobIdTraceCandidate');new=expanded('a','MechanicalDobSpikeAdmissionCandidate')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready','LatestOriginal_Admit',
            'PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','TighteningTask','ProtectedLoop_TaskService'):
            self.assertEqual(function(old,name),function(new,name),name)
        for stem in ('foc2_app_b/CMakeLists.txt','foc2_app_b/CMakePresets.json'):
            self.assertNotIn('FOC_DOB_SPIKE_ADMISSION',(ROOT/stem).read_text())
        warnings=[]
        for preset in ('MechanicalDobIdTraceCandidate','MechanicalDobSpikeAdmissionCandidate'):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warnings)

    def test_readonly_protocol_fits_existing_192_bytes(self):
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "mechanical_dob_monitor.h"
#include "dob_id_trace.h"
static MechanicalDobMonitor mechanical_dob_monitor;
static unsigned cl_armed,adc_fault,foc_fault;
static struct {unsigned state;} cl_session;
#define CL_RUNNING 2U
static uint32_t AS5047P_DmaNowUs(void){return 1000;}
'''+(ROOT/'firmware_common/mechanical_dob_binding.inc').read_text()+r'''
int main(void){char out[192];
dob_current_admission=(DobCurrentAdmission){.samples=0xffffffffU,.passed=0xffffffffU,
 .suspects=0xffffffffU,.isolated=0xffffffffU,.transitions=0xffffffffU,.unresolved=0xffffffffU,
 .held=0xffffffffU,.budget_exits=0xffffffffU,.decision=0xffffffffU,.blocked=0xffffffffU,.exit_reason=0xffffffffU};
const char *cmds[]={"MOTOR TEST MECH DOB ADMIT CFG","MOTOR TEST MECH DOB ADMIT","MOTOR TEST MECH DOB ADMIT STATS","MOTOR TEST MECH IDTRACE"};
for(unsigned i=0;i<4;i++){
 assert(MechanicalDob_Command(cmds[i],out,sizeof out));assert(strlen(out)<191&&strstr(out,"FEEDBACK=0"));
}
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ON",out,sizeof out));return 0;}
'''
        exe=ROOT/'tmp/dob-admission-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-DFOC_DOB_ID_TRACE=1','-DFOC_DOB_SPIKE_ADMISSION=1','-I',str(ROOT/'firmware_common'),
            str(ROOT/'firmware_common/dob_id_trace.c'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
            '-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True);self.assertEqual(p.returncode,0,p.stderr)


if __name__=='__main__':unittest.main()
