"""No debugger/serial/flash operations; compile actual diagnostic & PI source."""
import ctypes as ct
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_step_ab_report as report
import current_pi_compare as pi
from test_torque350_five_second import expanded
from test_torque_chain import function


class CurrentStepTests(unittest.TestCase):
    def test_actual_command_and_reference_binding(self):
        out=ROOT/'tmp/current-step-binding-host';out.mkdir(exist_ok=True)
        binding=(ROOT/'firmware_common/current_step_ab_binding.inc').read_text()
        binding=binding[:binding.index('__attribute__((optimize("Os")))\nstatic void TighteningTask')]
        # Generated fixture is the real source prefix, never a copied model.
        (out/'current_step_ab_test_binding.inc').write_text(binding,encoding='utf-8')
        exe=out/'binding.exe'
        p=subprocess.run([str(pi.GCC),'-O2','-std=c11','-Wall','-Wextra','-Werror',
            '-Wno-unused-function','-Wno-unused-variable','-I',str(out),'-I',str(ROOT/'firmware_common'),
            str(ROOT/'tests/current_step_ab_binding_host.c'),str(ROOT/'firmware_common/current_step_ab.c'),
            '-o',str(exe)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('PASS actual step binding',p.stdout)

    def test_actual_core_host(self):
        out=ROOT/'tmp/current-step-host';out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('step'+opt+'.exe')
            p=subprocess.run([str(pi.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/current_step_ab_host.c'),
                str(ROOT/'firmware_common/current_step_ab.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS current step AB',p.stdout)

    def test_same_actual_pi_runtime_gain_only_switch(self):
        # Actual main.c PI body, not a reimplementation of the controller.
        out=ROOT/'tmp/current-step-host';out.mkdir(exist_ok=True)
        code='''#include <math.h>
#include <stdint.h>
#define FOC_CURRENT_KP_V_PER_A .080f
#define FOC_CURRENT_KI_V_PER_AS 188.f
#define FOC_CURRENT_STEP_AB_DIAG 1
#include "current_pi_identified_candidate.h"
#define FOC_TS_S .00005f
#define FOC_CURRENT_FAULT_TRACE_ENABLE 0
#define FOC_INTEGRATOR_LIMIT_V .75f
#define FOC_VOLTAGE_LIMIT_V 1.60f
unsigned current_step_pi_new;
static float current_step_out_d,current_step_out_q;
static unsigned current_step_saturated;
typedef struct {float d,q;} State;
static float ClampFloat(float v,float a,float b){return v<a?a:v>b?b:v;}
__declspec(dllexport) void step(unsigned selected,State *s,float foc_id_ref_A,float foc_iq_ref_A,
float id_A,float iq_A,float *v) {
current_step_pi_new=selected;
float foc_int_d_V=s->d,foc_int_q_V=s->q,err_d,err_q,vd,vq,mag2,limit2;
'''+pi.pi_source()+'''
s->d=foc_int_d_V;s->q=foc_int_q_V;v[0]=vd;v[1]=vq;
}
'''
        dllfile=out/'switch.dll'
        p=subprocess.run([str(pi.GCC),'-O2','-std=c11','-shared','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(dllfile)],input=code,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        switch=ct.CDLL(str(dllfile));switch.step.argtypes=[ct.c_uint,ct.POINTER(pi.State)]+[ct.c_float]*4+[ct.POINTER(ct.c_float)]
        for selected in (0,1):
            normal,_=pi.compile_pi(bool(selected),out)
            a=pi.State();b=pi.State();va=(ct.c_float*2)();vb=(ct.c_float*2)()
            for k in range(1000):
                args=(0.,.3 if k<500 else -.2,.02,(k%7-3)*.1)
                normal.step(ct.byref(a),*args,va);switch.step(selected,ct.byref(b),*args,vb)
                self.assertEqual(bytes(a),bytes(b));self.assertEqual(list(va),list(vb))

    def test_protection_pipeline_angle_and_irq_unchanged(self):
        normal=expanded('a','CurrentPiIdentifiedCandidate');diag=expanded('a','CurrentStepAbDiagnostic')
        for name in ('ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_PwmCommitPermit',
                     'ProtectedLoop_TimerHealthy','ProtectedLoop_EmergencyOff','ProtectedLoop_Stop',
                     'ProtectedLoop_Pair','ProtectedLoop_TaskService','FOC_EncoderSpeedUpdate',
                     'FocCurrentValidation_Push','FOC_ResetController'):
            self.assertRegex(normal,r'\b'+name+r'\([^;{}]*\)\s*\{',name)
            self.assertEqual(function(normal,name),function(diag,name),name)
        binding=(ROOT/'firmware_common/current_step_ab_binding.inc').read_text()
        self.assertNotRegex(binding,r'TIM1->(?:CCR[1-3]|BDTR)\s*[|&]?=')
        self.assertNotIn('MotorControl_SetSpeed(',binding)
        self.assertIn('foc_id_ref_A=0.0f',binding)
        self.assertIn('CurrentStep_PositivePass',(ROOT/'firmware_common/current_step_ab.c').read_text())
        self.assertNotIn('current_step_ab',expanded('b','CurrentPiBUnchanged'))

    def test_normal_images_and_stable_b_unchanged(self):
        expected={
            'a/build/CurrentPiIdentifiedCandidate':'aaeee6b02372f9ecac2d8ec0ecb171f17bf87df41e54f43fe52b4ec9d404b56e',
            'a/build/CurrentPiLegacyCompare':'3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899',
            'b/build/FrictionBUnchanged':'7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366'}
        for path,digest in expected.items():
            image=ROOT/('foc2_app_'+path)/'foc2.bin'
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),digest)

    def test_report_abi_and_metrics(self):
        self.assertEqual(ct.sizeof(report.Capture),2576)
        s=report.Capture();s.state=3;s.completed=10;s.positive_pass=1
        for k,m in enumerate(s.metrics):
            target=round(abs(report.TARGETS[k])*10000)
            m.baseline_n=m.tail_n=100;m.high_n=600;m.valid_mask=63
            m.t10_us=100;m.t90_us=1100 if k%2==0 else 2100
            m.settle_us=3000 if k%2==0 else 4000;m.peak=target
            m.tail_sum=int(report.TARGETS[k]*10000)*100
            for j,r in enumerate(s.rows[k]):
                r.us=k*80000+(49950 if j==4 else 79950 if j==5 else 20000)
                r.flags=1
        safety=dict(first_fault=dict(valid=0),timing=dict(deadline_miss=0,actual_late_count=0,
            actual_commit_count=10000,actual_margin_min_us=12.))
        r=report.decode_capture(bytes(s),safety)
        self.assertTrue(all(x['verdict']=='NEW_MEETS_ALL' for x in r['comparisons']))
        self.assertAlmostEqual(r['segments'][0]['rise_10_90_ms'],1.)
        self.assertAlmostEqual(r['segments'][6]['peak_iq_a'],-.1)
        s.metrics[0].crossings=4
        self.assertTrue(report.decode_capture(bytes(s),safety)['segments'][0]['ringing'])
        safety['timing']['deadline_miss']=1
        self.assertFalse(report.decode_capture(bytes(s),safety)['timing_qualified'])
        self.assertEqual(report.decode_capture(bytes(s))['comparisons'][0]['verdict'],'INSUFFICIENT_EVIDENCE')
        s.state=2
        with self.assertRaises(ValueError):report.decode_capture(bytes(s))


if __name__=='__main__':unittest.main()
