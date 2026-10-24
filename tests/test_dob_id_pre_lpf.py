import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
from test_dob_persistent import FLAGS as BASE_FLAGS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_id_trace_report as report
FLAGS=BASE_FLAGS+['-DFOC_DOB_ID_PRE_LPF_QUALITY=1']

class PreLpfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binaries=[];cls.logs=[]
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-id-pre-lpf'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_id_pre_lpf_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),str(ROOT/'firmware_common/dob_id_trace.c'),
                '-o',str(exe)],capture_output=True,text=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            for args in ([],['binary'],['idbinary']):
                p=subprocess.run([str(exe),*args],capture_output=True)
                if p.returncode:raise AssertionError(p.stdout+p.stderr)
                if args:cls.binaries.append((args[0],p.stdout))
                else:cls.logs.append(p.stdout.decode())

    def test_production_c_single700mA_and_full_reproduced_sequence_no_lpf_pollution_or_reset(self):
        self.assertEqual(len(self.logs),2)
        for s in self.logs:
            self.assertIn('SINGLE_SPIKE before=0.0199999996 after=0.0199999996 hard_resets=0',s)
            self.assertIn('REPRODUCED_SPIKE quarantine_lpf=0.0227380954 hard_resets=0',s)
            self.assertIn('PERSISTENT_ID confirmed_us=20000 entry_resets=1 recovered=1',s)

    def test_actual_old_v6_board_capture_proves_root_cause_not_a_new_board_run(self):
        d=report.decode(ROOT/'tmp/mechanical-ident-run-1792730979256712900.json',
                        ROOT/'foc2_app_a/build/MechanicalDobPersistentCandidate/foc2.elf')
        self.assertTrue(d['board_verified']);rows=d['rows']
        i=next(i for i,x in enumerate(rows) if abs(x['id_meas_a']-.69978184)<1e-6)
        self.assertEqual(rows[i]['admission_name'],'JUMP_PENDING')
        self.assertAlmostEqual(rows[i-1]['abs_id_lpf_a'],.019953636,places=7)
        self.assertAlmostEqual(rows[i]['abs_id_lpf_a'],.052326411,places=7)

    def test_v7_rejection_reason_raw_delta_before_after_timer_reset_and_warmup(self):
        for mode,raw in self.binaries:
            if mode!='binary':continue
            d=report.decode_bytes(raw[:96],raw[96:]);self.assertTrue(d['complete'])
            self.assertEqual(d['meta']['abi'],7);self.assertEqual(len(d['rows']),72)
            prev,bad,returned,normal=d['rows'][15:19]
            self.assertEqual(bad['admission_name'],'QUALITY_WAIT')
            self.assertIn('ID_JUMP',bad['quality_reasons']);self.assertIn('WAIT',bad['quality_reasons'])
            self.assertAlmostEqual(bad['id_meas_a'],.700,places=6)
            self.assertAlmostEqual(bad['id_adjacent_delta_a'],.680,places=6)
            self.assertEqual(bad['abs_id_lpf_before_a'],bad['abs_id_lpf_a'])
            self.assertEqual(bad['abs_id_lpf_a'],prev['abs_id_lpf_a'])
            self.assertEqual(bad['id_bad_us'],prev['id_bad_us'])
            self.assertEqual(bad['warmup_s'],prev['warmup_s'])
            self.assertFalse(bad['lpf_updated'] or bad['valid'] or bad['reset_reason'])
            self.assertEqual(returned['admission_name'],'QUALITY_RETURN')
            self.assertTrue(returned['lpf_updated']);self.assertFalse(returned['valid'] or returned['reset'])
            self.assertAlmostEqual(returned['id_adjacent_delta_a'],-.680,places=6)
            self.assertEqual(returned['warmup_s'],prev['warmup_s'])
            self.assertTrue(normal['valid']);self.assertEqual(d['checks']['hold_lpf_change_a'],0)
            self.assertEqual(d['checks']['warmup_reset_violations'],0)
            self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)
            self.assertLess(d['checks']['max_warmup_increment_error_s'],1e-7)

    def test_sustained_real_level_not_deleted_forever_and_id_confirmed_then_recovered(self):
        for mode,raw in self.binaries:
            if mode!='idbinary':continue
            d=report.decode_bytes(raw[:96],raw[96:]);rows=d['rows'];bad1,bad2,level=rows[16:19]
            self.assertEqual([x['admission_name'] for x in (bad1,bad2,level)],
                             ['QUALITY_WAIT','QUALITY_WAIT','QUALITY_LEVEL'])
            self.assertEqual(bad1['abs_id_lpf_a'],bad2['abs_id_lpf_a'])
            self.assertGreater(level['abs_id_lpf_a'],bad2['abs_id_lpf_a'])
            entry=next(x for x in rows if x['reset_reason']==256)
            self.assertEqual(entry['id_bad_us'],20000)
            self.assertFalse(entry['valid'] or entry['initialized'])
            self.assertTrue(entry['id_bad_confirmed'])
            self.assertEqual(sum(x['reset_reason']==256 for x in rows),1)
            self.assertTrue(any(x['valid'] and not x['id_bad_confirmed'] for x in rows[40:]))
            self.assertEqual(d['checks']['warmup_reset_violations'],0)

    def test_decoder_rejects_pollution_fake_validity_and_reset_metadata(self):
        raw=next(raw for mode,raw in self.binaries if mode=='binary')
        # Trigger at index16, frame64: after-LPF float8; flags18; reset reason56.
        for offset,fmt,value in ((96+16*64+8,'<f',.0523),(96+16*64+56,'<I',1024),
                                 (96+16*64+60,'<I',(1<<19)|(1<<16))):
            b=bytearray(raw);struct.pack_into(fmt,b,offset,value)
            with self.assertRaises(ValueError):report.decode_bytes(b[:96],b[96:])

    def test_configuration_is_readonly_fits_192B_and_does_not_claim_physical_raw_cap(self):
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
assert(strstr(out,"MODE=PREFILTER JUMP_UA=100000 CONFIRM=3 ID_MAX_UA=60000 ID_US=20000 REF=TRUSTED GAP_US=10000 LATCH=0 FEEDBACK=0"));
assert(MechanicalDob_Command("MOTOR TEST MECH IDTRACE",out,sizeof out));
assert(strstr(out,"V=7 PRE=16 DENSE=24 TAIL=32 TAIL_US=16000"));
dob_current_admission.quality_reason=dob_current_admission.pending=dob_current_admission.jump_run=UINT32_MAX;
dob_current_admission.quality_recoveries=dob_current_admission.level_confirms=dob_current_admission.seed_confirms=UINT32_MAX;
dob_current_admission.filter_updated=UINT32_MAX;
assert(MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT QUALITY",out,sizeof out));
assert(strstr(out,"LPF_UPDATE=4294967295 FEEDBACK=0")&&strlen(out)<191);
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ADMIT ON",out,sizeof out));return 0;}
'''
        exe=ROOT/'tmp/dob-id-pre-lpf-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',*FLAGS,
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
            str(ROOT/'firmware_common/dob_id_trace.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True);self.assertEqual(p.returncode,0,p.stderr)

    def test_control_protection_and_warning_classes_frozen_b_default_off(self):
        presets=('MechanicalDobPersistentCandidate','MechanicalDobPreLpfCandidate')
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
        self.assertNotIn('FOC_DOB_ID_PRE_LPF_QUALITY',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

if __name__=='__main__':unittest.main()
