from pathlib import Path
import hashlib
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


class StartGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures={}
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-start-guard'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_DOB_ID_TRACE=1','-DFOC_DOB_SPIKE_ADMISSION=1','-DFOC_DOB_ADMISSION_START_GUARD=1',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_admission_start_guard_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),str(ROOT/'firmware_common/dob_id_trace.c'),
                '-o',str(exe)],text=True,capture_output=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            for mode in ('','isolated','blocked'):
                p=subprocess.run([str(exe)]+([mode] if mode else []),capture_output=True)
                if p.returncode:raise AssertionError(p.stderr)
                if mode:cls.fixtures[opt,mode]=p.stdout

    def test_native_arming_low_speed_quality_sign_and_no_latch_clear(self):
        self.assertEqual(len(self.fixtures),4)

    def test_first_event_during_acceleration_raw_pair_sources_and_exit_in_window(self):
        for (opt,mode),raw in self.fixtures.items():
            d=report.decode_bytes(raw[:96],raw[96:]);rows=d['rows']
            self.assertEqual(d['meta']['abi'],3);self.assertEqual(len(rows),96)
            self.assertTrue(d['complete']);self.assertEqual(d['meta']['stable_us'],0)
            spike=rows[16];self.assertEqual(spike['admission_name'],'SUSPECT');self.assertTrue(spike['trigger'])
            self.assertAlmostEqual(spike['id_meas_a'],-.56,places=6)
            self.assertEqual(spike['adc_source_us']-spike['timestamp_us'],115)
            self.assertEqual(spike['adc_published_us']-spike['adc_source_us'],19)
            self.assertEqual(spike['qualify_us'],50000);self.assertEqual(spike['speed_ref_rpm'],600)
            self.assertAlmostEqual(spike['speed_meas_rpm'],120,places=3)
            self.assertEqual(spike['adc_seq'],d['meta']['trigger_seq'])
            self.assertEqual(rows[17]['admission_name'],'BLOCKED' if mode=='blocked' else 'SPIKE_RETURN')
            if mode=='blocked':self.assertTrue(rows[17]['reset']);self.assertEqual(rows[17]['admission_exit_reason'],2)
            self.assertEqual(d['checks']['hold_lpf_change_a'],0)
            self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)
            self.assertEqual(d['checks']['warmup_reset_violations'],0)

    def test_old_v2_actual_board_capture_unchanged_and_decodable(self):
        d=report.decode(ROOT/'tmp/mechanical-ident-run-1792722888869886400.json',
            ROOT/'foc2_app_a/build/MechanicalDobSpikeAdmissionCandidate/foc2.elf')
        self.assertEqual(d['meta']['abi'],2);self.assertEqual(len(d['rows']),192)
        self.assertTrue(d['board_verified'])

    def test_readonly_guard_configuration_fits_192_bytes(self):
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
dob_current_admission.armed=dob_current_admission.qualify_us=dob_current_admission.prearm_samples=dob_current_admission.arm_us=0xffffffffU;
assert(MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ARM",out,sizeof out));
assert(strlen(out)<191&&strstr(out,"CONFIRM_US=50000 MIN_W_MRAD_S=2094")&&strstr(out,"ARM_US=4294967295 FEEDBACK=0"));
assert(MechanicalDob_Command("MOTOR TEST MECH IDTRACE",out,sizeof out));
assert(strstr(out,"V=3 PRE=16 DENSE=32 TAIL=48")&&strstr(out,"FEEDBACK=0"));
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ARM ON",out,sizeof out));return 0;}
'''
        exe=ROOT/'tmp/dob-start-guard-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-DFOC_DOB_ID_TRACE=1','-DFOC_DOB_SPIKE_ADMISSION=1','-DFOC_DOB_ADMISSION_START_GUARD=1',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
            str(ROOT/'firmware_common/dob_id_trace.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True);self.assertEqual(p.returncode,0,p.stderr)

    def test_control_protection_parameter_and_warning_freeze(self):
        presets=('MechanicalDobSpikeAdmissionCandidate','MechanicalDobAdmissionStartGuardCandidate')
        old,new=(expanded('a',p) for p in presets)
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready','LatestOriginal_Admit','ProtectedLoop_TaskService',
            'PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        warnings=[]
        for p in presets:
            directory=ROOT/'foc2_app_a/build'/p
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            process=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,text=True,capture_output=True)
            self.assertEqual(process.returncode,0,process.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',process.stderr)))
        self.assertEqual(*warnings)
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build/MechanicalDobSpikeAdmissionCandidate/foc2.bin').read_bytes()).hexdigest(),
            'e502d52c4c4d402f8a17a530aec9aa7925e11c1cf516d600da3cf7ff4dc862c0')
        self.assertNotIn('FOC_DOB_ADMISSION_START_GUARD',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())


if __name__=='__main__':unittest.main()
