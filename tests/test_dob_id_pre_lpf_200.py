import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import GCC, function
from test_torque350_five_second import expanded
from test_dob_id_pre_lpf import FLAGS as BASE_FLAGS

ROOT=Path(__file__).resolve().parents[1]
FLAGS=BASE_FLAGS+['-DDOB_ADMIT_JUMP_A=.200f']

class PreLpf200Tests(unittest.TestCase):
    def test_actual_readonly_protocol_reports_200ma(self):
        code=r'''
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "mechanical_dob_monitor.h"
#include "dob_id_trace.h"
static MechanicalDobMonitor mechanical_dob_monitor;
static unsigned cl_armed,adc_fault,foc_fault;
static struct {unsigned state;} cl_session;
#define CL_RUNNING 2U
static uint32_t AS5047P_DmaNowUs(void){return 1000;}
'''+(ROOT/'firmware_common/mechanical_dob_binding.inc').read_text()+r'''
int main(void){char out[192];
assert(MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT CFG",out,sizeof out));
assert(strstr(out,"MODE=PREFILTER JUMP_UA=200000 CONFIRM=3 ID_MAX_UA=60000 ID_US=20000 REF=TRUSTED GAP_US=10000 LATCH=0 FEEDBACK=0"));
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ON",out,sizeof out));
return 0;}
'''
        exe=ROOT/'tmp/dob-id-pre-lpf-200-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',*FLAGS,
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
            str(ROOT/'firmware_common/dob_id_trace.c'),'-x','c','-','-o',str(exe)],
            input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_production_signed_threshold_spikes_recovery_and_persistent_gate(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-id-pre-lpf-200'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_id_pre_lpf_200_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
                str(ROOT/'firmware_common/dob_id_trace.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS: signed 150/200mA admitted',p.stdout)

    def test_compiled_candidate_only_threshold_and_no_control_change(self):
        old,new=(expanded('a',p) for p in ('MechanicalDobPreLpfCandidate','MechanicalDobPreLpf200Candidate'))
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready','LatestOriginal_Admit',
            'ProtectedLoop_TaskService','PowerStage_Enable','PowerStage_Disable',
            'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        build=ROOT/'foc2_app_a/build/MechanicalDobPreLpf200Candidate'
        cmd=next(c['command'] for c in json.loads((build/'compile_commands.json').read_text())
                 if c['file'].endswith('/Core/Src/main.c'))
        self.assertIn('DOB_ADMIT_JUMP_A=.200f',cmd)
        p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -dM ',cmd),cwd=build,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('#define DOB_ADMIT_JUMP_A .200f',p.stdout)
        self.assertIn('#define DOB_ID_BAD_CONFIRM_US 20000U',p.stdout)
        self.assertNotIn('FOC_DOB_PRE_LPF_JUMP_200MA',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_old_board_image_remains_frozen_and_new_profile_is_opt_in(self):
        image=ROOT/'foc2_app_a/build/MechanicalDobPreLpfCandidate/foc2.bin'
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),
                         '018cdb371c9a3262af9998c766e4a66b13e0d1c95070f8d5a88ea72ed9de0809')
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        changed=[p['name'] for p in presets
                 if p.get('cacheVariables',{}).get('FOC_DOB_PRE_LPF_JUMP_200MA')=='ON']
        self.assertEqual(changed,['MechanicalDobPreLpf200Candidate'])

if __name__=='__main__':unittest.main()
