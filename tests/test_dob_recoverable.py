import csv
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_id_trace_report as report
FLAGS=['-DFOC_DOB_ID_TRACE=1','-DFOC_DOB_SPIKE_ADMISSION=1',
       '-DFOC_DOB_ADMISSION_START_GUARD=1','-DFOC_DOB_DIRECT_JUMP_REJECT=1',
       '-DFOC_DOB_RECOVERABLE_ADMISSION=1']

class RecoverableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binaries=[];cls.executables=[]
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-recoverable'+opt+'.exe');cls.executables.append(exe)
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_recoverable_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),str(ROOT/'firmware_common/dob_id_trace.c'),
                '-o',str(exe)],capture_output=True,text=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            for args in ([],['binary']):
                p=subprocess.run([str(exe),*args],capture_output=True)
                if p.returncode:raise AssertionError(p.stdout+p.stderr)
                if args:cls.binaries.append(p.stdout)

    def test_native_no_count_latch_actual_old_latch_fixture_and_gap_rewarm(self):
        self.assertEqual(len(self.binaries),2)

    def test_trace_short_gaps_do_not_filter_reset_or_earn_warmup(self):
        for raw in self.binaries:
            d=report.decode_bytes(raw[:96],raw[96:]);self.assertEqual(d['meta']['abi'],5)
            self.assertTrue(d['complete']);self.assertEqual(len(d['rows']),96)
            a,b,c,n=d['rows'][16:20]
            self.assertEqual([x['admission_name'] for x in (a,b,c,n)],
                             ['DIRECT_REJECT','DIRECT_REJECT','GAP_RECOVERY','NORMAL'])
            self.assertFalse(any(x['reset'] or x['valid'] for x in (a,b,c)))
            self.assertTrue(n['valid']);self.assertEqual(a['warmup_s'],c['warmup_s'])
            self.assertEqual(d['checks']['hold_lpf_change_a'],0)
            self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)
            self.assertLess(d['checks']['max_warmup_increment_error_s'],1e-7)
            self.assertEqual(d['checks']['warmup_reset_violations'],0)
            self.assertGreater(d['rows'][-1]['relative_ms'],750)

    def test_actual_continuous_dense_rows_not_decimated_tail(self):
        d=json.loads((ROOT/'tmp/dob-direct100-board-1792725957959011200.json').read_text())
        rows=d['rows'][:48];seed=next(i for i,x in enumerate(rows) if x['admission_name']=='SEED');rows=rows[seed:]
        self.assertEqual(len(rows),45)
        for a,b in zip(rows,rows[1:]):self.assertEqual(b['timestamp_us']-a['timestamp_us'],b['interval_us'])
        stimulus=''.join(f"{x['timestamp_us']} {x['interval_us']} {x['id_meas_a']:.9g} {x['iq_meas_a']:.9g}\n" for x in rows)
        for exe in self.executables:
            p=subprocess.run([str(exe),'replay'],input=stimulus,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr)
            got=list(csv.DictReader(io.StringIO(p.stdout)))
            self.assertEqual(sum(x['result']=='0' for x in got),5)
            self.assertFalse(any(x['blocked']=='1' for x in got))
            i=next(i for i,x in enumerate(rows) if x['relative_ms']==21.001)
            self.assertEqual(got[i]['decision'],'11')

    def test_control_protection_frozen_b_default_off(self):
        presets=('MechanicalDobDirect100Candidate','MechanicalDobRecoverableCandidate')
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
        self.assertNotIn('FOC_DOB_RECOVERABLE_ADMISSION',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_readonly_config_and_buffer_capacity(self):
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
assert(strstr(out,"MODE=SKIP JUMP_UA=100000 ID_MAX_UA=60000 REF=RAW GAP_US=10000 LATCH=0 FEEDBACK=0"));
assert(strlen(out)<191);
assert(MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT GAPS",out,sizeof out));
assert(strstr(out,"STALE=0 RESET=0 RECOVER=0 GAP_US=0 FEEDBACK=0"));
assert(MechanicalDob_Command("MOTOR TEST MECH IDTRACE",out,sizeof out));
assert(strstr(out,"V=5 PRE=16 DENSE=32 TAIL=48 TAIL_US=16000"));
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ON",out,sizeof out));return 0;}
'''
        exe=ROOT/'tmp/dob-recoverable-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',*FLAGS,
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
            str(ROOT/'firmware_common/dob_id_trace.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True);self.assertEqual(p.returncode,0,p.stderr)

if __name__=='__main__':unittest.main()
