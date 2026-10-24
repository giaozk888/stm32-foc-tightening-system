import csv
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
from test_dob_recoverable import FLAGS as BASE_FLAGS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_id_trace_report as report
FLAGS=BASE_FLAGS+['-DFOC_DOB_PERSISTENT_QUALITY=1']

class PersistentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binaries=[];cls.executables=[]
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-persistent'+opt+'.exe');cls.executables.append(exe)
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_persistent_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),str(ROOT/'firmware_common/dob_id_trace.c'),
                '-o',str(exe)],text=True,capture_output=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            for args in ([],['binary'],['idbinary']):
                p=subprocess.run([str(exe),*args],capture_output=True)
                if p.returncode:raise AssertionError(p.stdout+p.stderr)
                if args:cls.binaries.append((args[0],p.stdout))

    def test_native_boundaries_time_not_count_interruptions_recovery_and_real_fault(self):
        self.assertEqual(len(self.binaries),4)

    def test_v6_pending_admitted_third_excluded_and_no_warmup_reset(self):
        for mode,raw in self.binaries:
            if mode!='binary':continue
            d=report.decode_bytes(raw[:96],raw[96:]);self.assertTrue(d['complete'])
            self.assertEqual(d['meta']['abi'],6);self.assertEqual(len(d['rows']),96)
            a,b,c,h,recovery,normal=d['rows'][16:22]
            self.assertEqual([x['admission_name'] for x in (a,b,c,h,recovery,normal)],
                ['JUMP_PENDING','JUMP_PENDING','RUN_REJECT','RUN_REJECT','GAP_RECOVERY','NORMAL'])
            self.assertTrue(a['valid'] and b['valid'] and normal['valid'])
            self.assertFalse(any(x['valid'] or x['reset'] for x in (c,h,recovery)))
            self.assertEqual([a['jump_run'],b['jump_run'],c['jump_run'],h['jump_run']],[1,2,3,4])
            self.assertEqual(c['warmup_s'],recovery['warmup_s'])
            self.assertEqual(d['checks']['hold_lpf_change_a'],0)
            self.assertEqual(d['checks']['warmup_reset_violations'],0)
            self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)
            self.assertLess(d['checks']['max_warmup_increment_error_s'],1e-7)

    def test_v6_id_confirm_timer_single_reset_then_rewarm(self):
        for mode,raw in self.binaries:
            if mode!='idbinary':continue
            d=report.decode_bytes(raw[:96],raw[96:]);rows=d['rows']
            before,entry,after=rows[15:18]
            self.assertEqual(before['id_bad_us'],19000);self.assertTrue(before['valid'])
            self.assertFalse(before['id_bad_confirmed'] or before['reset'])
            self.assertEqual(entry['id_bad_us'],20000);self.assertTrue(entry['id_bad_confirmed'] and entry['reset'])
            self.assertFalse(entry['valid'] or entry['initialized']);self.assertEqual(entry['status'],256)
            self.assertTrue(after['id_bad_confirmed']);self.assertFalse(after['valid'] or after['reset'])
            self.assertEqual(d['checks']['warmup_reset_violations'],0)
            self.assertTrue(any(x['valid'] and not x['id_bad_confirmed'] for x in rows[32:]))

    def test_actual_retained_dense_replay_not_counterfactual_full_run(self):
        rows=json.loads((ROOT/'tmp/dob-direct100-board-1792725957959011200.json').read_text())['rows'][:48]
        seed=next(i for i,x in enumerate(rows) if x['admission_name']=='SEED');rows=rows[seed:]
        stimulus=''.join(f"{x['timestamp_us']} {x['interval_us']} {x['id_meas_a']:.9g} {x['iq_meas_a']:.9g}\n" for x in rows)
        for exe in self.executables:
            p=subprocess.run([str(exe),'replay'],input=stimulus,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr);got=list(csv.DictReader(io.StringIO(p.stdout)))
            self.assertEqual(sum(x['decision']=='15' for x in got),1)
            self.assertEqual(sum(x['decision']=='14' for x in got),4)
            self.assertFalse(any(x['blocked']=='1' for x in got))

    def test_v6_corrupt_confirmation_metadata_rejected(self):
        raw=next(raw for mode,raw in self.binaries if mode=='binary')
        # Dense third-jump frame at physical index18: packed run must be>=3.
        b=bytearray(raw);struct.pack_into('<H',b,96+18*48+22,2)
        with self.assertRaises(ValueError):report.decode_bytes(b[:96],b[96:])
        raw=next(raw for mode,raw in self.binaries if mode=='idbinary')
        b=bytearray(raw);struct.pack_into('<I',b,96+16*48+44,19000)
        with self.assertRaises(ValueError):report.decode_bytes(b[:96],b[96:])

    def test_readonly_config_duration_and_extreme_protocol_capacity(self):
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
assert(strstr(out,"MODE=PERSIST JUMP_UA=100000 POINTS=3 ID_MAX_UA=60000 ID_US=20000 REF=RAW GAP_US=10000 LATCH=0 FEEDBACK=0"));
assert(MechanicalDob_Command("MOTOR TEST MECH IDTRACE",out,sizeof out));assert(strstr(out,"V=6 PRE=16 DENSE=32 TAIL=48 TAIL_US=16000"));
dob_current_admission.jump_run=dob_current_admission.jump_max_run=UINT32_MAX;
dob_current_admission.jump_pending_samples=dob_current_admission.id_bad_us=UINT32_MAX;
dob_current_admission.id_bad_peak_us=dob_current_admission.id_bad_entries=dob_current_admission.id_bad_recoveries=UINT32_MAX;
dob_current_admission.id_bad_latched=1;
assert(MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT PERSIST",out,sizeof out));
assert(strstr(out,"ID_RECOVER=4294967295 FEEDBACK=0")&&strlen(out)<191);
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ON",out,sizeof out));return 0;}
'''
        exe=ROOT/'tmp/dob-persistent-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',*FLAGS,
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
            str(ROOT/'firmware_common/dob_id_trace.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True);self.assertEqual(p.returncode,0,p.stderr)

    def test_control_protection_defaults_and_warning_classes_unchanged(self):
        presets=('MechanicalDobRecoverableCandidate','MechanicalDobPersistentCandidate')
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
        self.assertNotIn('FOC_DOB_PERSISTENT_QUALITY',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

if __name__=='__main__':unittest.main()
