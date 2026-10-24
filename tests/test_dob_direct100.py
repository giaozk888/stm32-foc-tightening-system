from pathlib import Path
import csv
import io
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


class Direct100Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures=[];cls.executables=[]
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-direct100'+opt+'.exe');cls.executables.append(exe)
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_DOB_ID_TRACE=1','-DFOC_DOB_SPIKE_ADMISSION=1','-DFOC_DOB_ADMISSION_START_GUARD=1',
                '-DFOC_DOB_DIRECT_JUMP_REJECT=1','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/dob_direct100_host.c'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
                str(ROOT/'firmware_common/dob_id_trace.c'),'-o',str(exe)],text=True,capture_output=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            for args in ([],['binary']):
                p=subprocess.run([str(exe)]+args,capture_output=True)
                if p.returncode:raise AssertionError(p.stdout+p.stderr)
                if args:cls.fixtures.append(p.stdout)

    def test_native_threshold_signs_paired_exclusion_warmup_and_original_exit_limits(self):
        self.assertEqual(len(self.fixtures),2)

    def test_v4_no_false_spike_confirmation_or_transition_and_no_reset(self):
        for raw in self.fixtures:
            d=report.decode_bytes(raw[:96],raw[96:]);self.assertEqual(d['meta']['abi'],4)
            self.assertTrue(d['complete']);rows=d['rows'];self.assertEqual(len(rows),96)
            bad,returning,normal=rows[16:19]
            self.assertEqual(bad['admission_name'],'DIRECT_REJECT');self.assertTrue(bad['trigger'])
            self.assertEqual(returning['admission_name'],'GAP_RECOVERY')
            self.assertEqual(normal['admission_name'],'NORMAL')
            self.assertFalse(bad['reset'] or bad['valid'] or returning['reset'] or returning['valid'])
            self.assertTrue(normal['valid']);self.assertEqual(bad['warmup_s'],returning['warmup_s'])
            self.assertEqual(d['checks']['hold_lpf_change_a'],0)
            self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)
            self.assertLess(d['checks']['max_warmup_increment_error_s'],1e-7)

    def test_actual_retained_dense_segment_replay_not_whole_session(self):
        r=json.loads((ROOT/'tmp/mechanical-ident-run-1792724932372082300.json').read_text())
        rows=r['idtrace_capture']['rows'][:48]
        stimulus=''.join(f"{x['timestamp_us']} {x['interval_us']} {x['id_meas_a']:.9g} {x['iq_meas_a']:.9g}\n" for x in rows)
        p=subprocess.run([str(self.executables[0]),'replay'],input=stimulus,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        result=list(csv.DictReader(io.StringIO(p.stdout)))
        # The high point formerly accepted at index15 is now immediately
        # excluded and its lower return is NOT classified as a new level.
        self.assertEqual(result[15]['decision'],'10')
        self.assertEqual(result[16]['decision'],'11')
        self.assertEqual(result[17]['decision'],'0')
        self.assertFalse(any(x['decision'] in ('2','3','4','5') for x in result))
        cls=type(self);cls.replay_summary=dict(rows=len(result),reference='first retained dense pair, not full-session seed',
            excluded=sum(x['decision']=='10' for x in result),blocked=any(x['blocked']=='1' for x in result))

    def test_v3_actual_capture_still_decodes_with_original_provenance(self):
        d=report.decode(ROOT/'tmp/mechanical-ident-run-1792724932372082300.json',
            ROOT/'foc2_app_a/build/MechanicalDobAdmissionStartGuardCandidate/foc2.elf')
        self.assertTrue(d['board_verified']);self.assertEqual(d['meta']['abi'],3)

    def test_control_protection_and_warning_freeze_b_default_off(self):
        presets=('MechanicalDobAdmissionStartGuardCandidate','MechanicalDobDirect100Candidate')
        old,new=(expanded('a',p) for p in presets)
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready','LatestOriginal_Admit','ProtectedLoop_TaskService',
            'PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        warnings=[]
        for preset in presets:
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr);warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warnings)
        self.assertNotIn('FOC_DOB_DIRECT_JUMP_REJECT',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_readonly_direct_configuration_and_trace_identity(self):
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
assert(MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT CFG",out,sizeof out));
assert(strstr(out,"MODE=DIRECT JUMP_UA=100000 ID_MAX_UA=60000 REF=ACCEPTED")&&strstr(out,"FEEDBACK=0"));
assert(!strstr(out,"RETURN")&&!strstr(out,"CONFIRM_UA"));
assert(MechanicalDob_Command("MOTOR TEST MECH IDTRACE",out,sizeof out));
assert(strstr(out,"V=4 PRE=16 DENSE=32 TAIL=48")&&strlen(out)<191);
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ON",out,sizeof out));return 0;}
'''
        exe=ROOT/'tmp/dob-direct100-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-DFOC_DOB_ID_TRACE=1','-DFOC_DOB_SPIKE_ADMISSION=1','-DFOC_DOB_ADMISSION_START_GUARD=1',
            '-DFOC_DOB_DIRECT_JUMP_REJECT=1','-I',str(ROOT/'firmware_common'),
            str(ROOT/'firmware_common/mechanical_dob_monitor.c'),str(ROOT/'firmware_common/dob_id_trace.c'),
            '-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True);self.assertEqual(p.returncode,0,p.stderr)


if __name__=='__main__':unittest.main()
