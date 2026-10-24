from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_id_trace_report as report
import dob_id_trace_board as board


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw={}
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-id-trace'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-DFOC_DOB_ID_TRACE=1',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_id_trace_host.c'),
                str(ROOT/'firmware_common/dob_id_trace.c'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
                '-o',str(exe)],text=True,capture_output=True)
            if p.returncode:raise AssertionError(p.stdout+p.stderr)
            for mode in (0,1,2,3,4):
                p=subprocess.run([str(exe),str(mode)],capture_output=True)
                if p.returncode:raise AssertionError(str(mode)+str(p.stderr))
                cls.raw[opt,mode]=p.stdout

    def test_actual_c_same_epoch_hook_dense_lpf_and_warmup_recovery(self):
        for opt in ('-Os','-O2'):
            raw=self.raw[opt,0];d=report.decode_bytes(raw[:96],raw[96:])
            self.assertTrue(d['triggered'] and d['complete'])
            self.assertEqual(len(d['rows']),288)
            self.assertEqual(d['meta']['reset_calls_total'],5)
            self.assertEqual(len(d['reset_events']),5)
            self.assertEqual(d['rows'][64]['relative_ms'],0)
            self.assertAlmostEqual(d['rows'][64]['id_meas_a'],.30,places=6)
            self.assertAlmostEqual(d['rows'][64]['abs_id_lpf_a'],.0523809524,places=7)
            self.assertEqual([r['warmup_s'] for r in d['rows'][64:69]],[0]*5)
            self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)
            self.assertLess(d['checks']['max_warmup_increment_error_s'],1e-7)
            self.assertEqual(d['checks']['warmup_reset_violations'],0)
            self.assertTrue(any(r['valid'] for r in d['rows'][128:]))

    def test_no_id_reject_is_explicit_not_triggered_not_failure(self):
        r=self.raw['-Os',1];d=report.decode_bytes(r[:96],r[96:])
        self.assertFalse(d['triggered'] or d['complete']);self.assertEqual(len(d['rows']),64)

    def test_wrap_and_jitter_reconstruct_forward_time(self):
        r=self.raw['-Os',2];d=report.decode_bytes(r[:96],r[96:])
        times=[r['relative_ms'] for r in d['rows']]
        self.assertEqual(times,sorted(times));self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)

    def test_corrupt_trace_rejected(self):
        raw=self.raw['-Os',0]
        for off,value in ((0,2),(8,1),(12,0),(24,65),(32,161),(44,100)):
            h=bytearray(raw[:96]);struct.pack_into('<I',h,off,value)
            with self.assertRaises(ValueError):report.decode_bytes(h,raw[96:])
        buf=bytearray(raw[96:]);struct.pack_into('<f',buf,64*16,float('nan'))
        with self.assertRaises(ValueError):report.decode_bytes(raw[:96],buf)

    def test_bad_time_is_explicit_partial_and_quality_gap_reseeds(self):
        r=self.raw['-Os',3];d=report.decode_bytes(r[:96],r[96:])
        self.assertEqual(d['meta']['state'],5);self.assertEqual(d['meta']['encoding_errors'],1)
        self.assertFalse(d['complete'])
        r=self.raw['-Os',4];d=report.decode_bytes(r[:96],r[96:])
        self.assertTrue(d['rows'][84]['reset']);self.assertIn('CURRENT',d['rows'][84]['reasons'])
        self.assertTrue(d['rows'][85]['filter_seeded'])
        self.assertLess(d['checks']['max_lpf_residual_a'],1e-7)

    def test_readonly_protocol_real_buffer_capacity(self):
        binding=(ROOT/'firmware_common/mechanical_dob_binding.inc').read_text()
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
'''+binding+r'''
int main(void){char out[192];
dob_id_trace.state=dob_id_trace.post_count=dob_id_trace.tail_count=dob_id_trace.reset_calls_total=0xffffffffU;
assert(MechanicalDob_Command("MOTOR TEST MECH IDTRACE",out,sizeof out));
assert(strlen(out)<191 && strstr(out,"RESET=4294967295 FEEDBACK=0"));
assert(!MechanicalDob_Command("MOTOR TEST MECH IDTRACE ON",out,sizeof out));
return 0;}
'''
        exe=ROOT/'tmp/dob-id-trace-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-DFOC_DOB_ID_TRACE=1',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/dob_id_trace.c'),
            str(ROOT/'firmware_common/mechanical_dob_monitor.c'),'-x','c','-','-o',str(exe)],
            input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True);self.assertEqual(p.returncode,0,p.stderr)

    def test_files_only_identity_and_original_b1047(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_id_trace_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('1 mechanical points; no devices',p.stdout)
        board.image();r=__import__('json').loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_'] and r['b_application_not_run']);self.assertEqual(r['metadata'][5],1047)
        self.assertEqual(r['image_sha256'],board.previous.SHA)

    def test_fresh_physical_gates_before_setup(self):
        for args in (['--prepare-off'],['--execute-once','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()

    def test_unused_trace_before_existing_readiness_and_single_run(self):
        def new():b=object.__new__(board.TraceBoard);b.record={};return b
        initial='1 OK IDTRACE V=1 PRE=64 DENSE=64 TAIL=160 TAIL_US=4000 STATE=0 POST=0 NT=0 RESET=0 FEEDBACK=0'
        with patch.object(board.shadow.DobBoard,'command',side_effect=[initial,'OK QUEUED']) as send:
            new().command('MOTOR TEST MECH RUN POS 600');self.assertEqual(send.call_count,2)
        with patch.object(board.shadow.DobBoard,'command',return_value=initial.replace('RESET=0','RESET=1')) as send:
            with self.assertRaises(RuntimeError):new().command('MOTOR TEST MECH RUN POS 600')
            self.assertEqual(send.call_count,1)
        with patch.object(board.shadow.DobBoard,'command') as send:
            with self.assertRaises(ValueError):new().command('MOTOR TEST MECH RUN NEG 600')
            send.assert_not_called()

    def test_frozen_foc_protections_pipeline_and_no_new_warning_class(self):
        import re,json
        old=expanded('a','MechanicalDobShadowCandidate');new=expanded('a','MechanicalDobIdTraceCandidate')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready','LatestOriginal_Admit',
            'PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        warnings=[]
        for preset in ('MechanicalDobShadowCandidate','MechanicalDobIdTraceCandidate'):
            d=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((d/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=d,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warnings)


if __name__=='__main__':unittest.main()
