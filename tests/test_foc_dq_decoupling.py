"""Actual A PI source, cross-coupling math and non-actuating host checks."""
import ctypes as ct
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_pi_compare as pi
from test_torque350_five_second import expanded
from test_torque_chain import function


class DqTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out=ROOT/'tmp/dq-host';out.mkdir(exist_ok=True)
        cls.dlls=[]
        for compiled in (0,1):
            code=r'''
#include <math.h>
#include <stdint.h>
#include "foc_dq_decoupling.h"
#include "current_pi_identified_candidate.h"
#define FOC_CURRENT_KP_V_PER_A .080f
#define FOC_CURRENT_KI_V_PER_AS 188.f
#define FOC_CURRENT_FAULT_TRACE_ENABLE 0
#define FOC_TS_S .00005f
#define FOC_INTEGRATOR_LIMIT_V .75f
#define FOC_VOLTAGE_LIMIT_V 1.60f
#define CL_BAD_OUTPUT 16
static unsigned faults;
static void ProtectedLoop_EmergencyOff(unsigned x) {faults=x;}
static float ClampFloat(float x,float lo,float hi){return x<lo?lo:x>hi?hi:x;}
static unsigned char dq_decoupling_enabled;
static float encoder_omega_e_rad_s;
static FocDqDecouplingFrame dq_decoupling_frame;
static unsigned injected_seq_count;
static struct {unsigned source_us;} cl_frame;
__declspec(dllexport) void step(float *state,float ref_d,float ref_q,
float id_A,float iq_A,float omega,unsigned on,float *out) {
float foc_id_ref_A=ref_d,foc_iq_ref_A=ref_q;
float foc_int_d_V=state[0],foc_int_q_V=state[1];
float vd,vq,err_d,err_q,mag2,limit2;
dq_decoupling_enabled=(unsigned char)on;encoder_omega_e_rad_s=omega;
injected_seq_count++;cl_frame.source_us=injected_seq_count*50;
''' + pi.pi_source() + r'''
state[0]=foc_int_d_V;state[1]=foc_int_q_V;
out[0]=vd;out[1]=vq;out[2]=dq_decoupling_frame.vd_ff;
out[3]=dq_decoupling_frame.vq_ff;out[4]=(float)dq_decoupling_frame.saturated;
}
__declspec(dllexport) unsigned apply(unsigned on,float w,float d,float q,float *out) {
return FocDqDecoupling_Apply((uint8_t)on,w,d,q,out,out+1);}
'''
            dll=out/f'dq{compiled}.dll'
            p=subprocess.run([str(pi.GCC),'-std=c11','-O2','-shared','-Wall','-Wextra',
                '-Werror','-Wno-unused-function','-Wno-unused-variable',
                '-DFOC_CURRENT_PI_IDENTIFIED_ENABLE=1',
                *(['-DFOC_DQ_DECOUPLING_CANDIDATE=1'] if compiled else []),
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(dll)],
                input=code,text=True,capture_output=True)
            if p.returncode:raise RuntimeError(p.stdout+p.stderr)
            lib=ct.CDLL(str(dll));cls.dlls.append(lib)
            lib.step.argtypes=[ct.POINTER(ct.c_float)]+[ct.c_float]*5+[ct.c_uint,ct.POINTER(ct.c_float)]
            lib.step.restype=None
            lib.apply.argtypes=[ct.c_uint]+[ct.c_float]*3+[ct.POINTER(ct.c_float)]
            lib.apply.restype=ct.c_uint

    def test_cross_coupling_sign_units_zero_and_reverse(self):
        lib=self.dlls[1];o=(ct.c_float*2)()
        for w in (-251.327412,0,251.327412): # +/-240 mechanical rpm, 10 pairs
            for d,q in ((0,.5),(.3,-.2),(-.3,.2)):
                self.assertEqual(lib.apply(1,w,d,q,o),1)
                self.assertAlmostEqual(o[0],-w*.00001118*q,places=8)
                self.assertAlmostEqual(o[1], w*.00002003*d,places=8)

    def test_disabled_and_nonfinite_fail_closed(self):
        lib=self.dlls[1];o=(ct.c_float*2)()
        for args in ((1,float('nan'),0,.1),(1,1,float('inf'),.1),(1,1,0,float('inf')),
                     (1,3e38,0,3e38)):
            self.assertEqual(lib.apply(*args,o),0)
            self.assertEqual(list(o),[0.,0.])
        self.assertEqual(lib.apply(0,float('nan'),float('nan'),float('nan'),o),1)
        self.assertEqual(list(o),[0.,0.])

    def test_runtime_off_bitwise_existing_actual_pi(self):
        states=[(ct.c_float*2)(),(ct.c_float*2)()]
        for k in range(350):
            outputs=[]
            for lib,state in zip(self.dlls,states):
                o=(ct.c_float*5)()
                lib.step(state,.1 if k%2 else -.3,.5,-.1,.1,250,0,o)
                outputs.append(bytes(state)+bytes(o)[:8])
            self.assertEqual(*outputs)

    def test_total_vector_limit_and_tracking_subtracts_ff(self):
        lib=self.dlls[1];s=(ct.c_float*2)(.01,-.02);o=(ct.c_float*5)()
        # Deliberate synthetic extreme to exercise common voltage saturation.
        lib.step(s,.25,.25,.25,.25,1000000,1,o)
        self.assertAlmostEqual((o[0]**2+o[1]**2)**.5,1.6,places=6)
        self.assertEqual(o[4],1)
        for ax in (0,1):
            expected=max(-.75,min(.75,o[ax]-o[2+ax])) # error is exactly zero
            self.assertAlmostEqual(s[ax],expected,places=6)

    def test_unsaturated_current_pi_addition(self):
        lib=self.dlls[1];s=(ct.c_float*2)();o=(ct.c_float*5)()
        lib.step(s,.1,.4,.05,.2,251.327412,1,o)
        self.assertEqual(o[4],0)
        self.assertAlmostEqual(o[0],.0377556644*.05+s[0]+o[2],places=7)
        self.assertAlmostEqual(o[1],.0210738052*.2+s[1]+o[3],places=7)

    def test_actual_equations_cancel_only_inductive_plant_cross_terms(self):
        # Algebra/assumed model only, not a measured motor response.
        o=(ct.c_float*2)();w=251.327412;d=.15;q=.4
        self.dlls[1].apply(1,w,d,q,o)
        self.assertAlmostEqual(o[0]+w*.00001118*q,0,places=8)
        self.assertAlmostEqual(o[1]-w*.00002003*d,0,places=8)

    def test_pipeline_guards_angle_irq_b_frozen_between_presets(self):
        before=expanded('a','CurrentPiIdentifiedCandidate')
        after=expanded('a','DqDecouplingCandidate')
        for name in ('FOC_EncoderSpeedUpdate','Encoder_ElectricalAngleRad',
                     'ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty',
                     'ProtectedLoop_TimerHealthy','ProtectedLoop_AdcIrq',
                     'ProtectedLoop_GuardIrqBody','PowerStage_Enable','PowerStage_Disable',
                     'TighteningTask','MotorControl_SetIq'):
            self.assertEqual(function(before,name),function(after,name),name)
        # Check the selected real FOC branch; raw conditional alternatives can
        # contain mutually exclusive opening/closing braces.
        f=function(after,'FOC_CurrentLoopStep')
        self.assertLess(f.index('FocDqDecoupling_Apply'),f.index('mag2 = vd * vd'))
        self.assertNotIn('printf',f)
        b=ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
                         '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')
        self.assertNotIn('FOC_DQ_DECOUPLING', (ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_default_opt_in_local_idle_toggle_and_latest_binary_only(self):
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertIn('voltage feedforward" OFF)',cm)
        binding=(ROOT/'firmware_common/foc_dq_decoupling_binding.inc').read_text()
        self.assertIn('TIM1->CCER',binding)
        self.assertIn('cl_session.state==CL_RUNNING',binding)
        self.assertLess(binding.index('__set_PRIMASK(mask);\n    if'),
                        binding.index('"OK DQ VALID='))
        self.assertNotIn('LatestOriginal_Admit',binding)
        self.assertNotIn('HAL_GPIO_WritePin',binding)
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        on=next(p for p in presets['configurePresets'] if p['name']=='DqDecouplingCandidate')
        self.assertEqual(on['inherits'],'CurrentPiIdentifiedCandidate')

    def test_real_console_idle_toggle_refuses_live_output_and_preserves_state(self):
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "foc_dq_decoupling.h"
#define CL_RUNNING 2
#define MOTOR_MODE_IDLE 0
#define TIM_BDTR_MOE 0x8000u
#define TIM_BDTR_AOE 0x4000u
#define DRIVER_SD_Pin 64u
static struct {unsigned state;} cl_session;
static struct {unsigned ODR;} gpio;
static struct {unsigned BDTR,CCER;} tim;
#define DRIVER_SD_GPIO_Port (&gpio)
#define TIM1 (&tim)
static unsigned busy,tightening_start_request,tightening_stop_request,motor_control_mode,mask;
static unsigned Tightening_IsBusy(void){return busy;}
static unsigned __get_PRIMASK(void){return mask;}
static void __disable_irq(void){mask=1;}
static void __set_PRIMASK(unsigned x){mask=x;}
static unsigned char dq_decoupling_enabled;
static FocDqDecouplingFrame dq_decoupling_frame;
#include "foc_dq_decoupling_binding.inc"
int main(void){char out[384];
assert(!DqDecoupling_Command("MOTOR TEST FF STATUS",out,sizeof out));
assert(DqDecoupling_Command("MOTOR TEST DQ ON",out,sizeof out));
assert(dq_decoupling_enabled && !mask && !dq_decoupling_frame.valid);
unsigned *blockers[]={&cl_session.state,&busy,&tightening_start_request,
 &tightening_stop_request,&motor_control_mode,&gpio.ODR,&tim.BDTR,&tim.CCER};
for(unsigned k=0;k<sizeof blockers/sizeof blockers[0];k++){
 *blockers[k]=k==0?CL_RUNNING:k==5?DRIVER_SD_Pin:k==6?TIM_BDTR_MOE:1;
 assert(DqDecoupling_Command("MOTOR TEST DQ OFF",out,sizeof out));
 assert(strstr(out,"ERR DQ BUSY") && dq_decoupling_enabled && !mask);
 *blockers[k]=0;
}
assert(DqDecoupling_Command("MOTOR TEST DQ OFF",out,sizeof out));
assert(!dq_decoupling_enabled && !mask);
assert(DqDecoupling_Command("MOTOR TEST DQ STATUS",out,sizeof out));
assert(strstr(out,"ON=0") && strstr(out,"VALID=0"));
assert(DqDecoupling_Command("MOTOR TEST DQ VOLTAGE",out,sizeof out));
assert(strstr(out,"VALID=0") && strstr(out,"VD_FF_UV=0"));
assert(DqWire_Scaled(-.5f,1e6f)==-500000);
assert(DqWire_Scaled(NAN,1e6f)==INT32_MIN);
assert(DqWire_Scaled(1e30f,1e6f)==INT32_MIN);
assert(DqDecoupling_Command("MOTOR TEST DQ STATUS",out,sizeof out));
assert(strstr(out,"LD_NH=20030") && strstr(out,"LQ_NH=11180"));
return 0;}
'''
        exe=ROOT/'tmp/dq-host/console.exe'
        p=subprocess.run([str(pi.GCC),'-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
            input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_nano_printf_wire_format_is_integer_only(self):
        source=(ROOT/'firmware_common/foc_dq_decoupling_binding.inc').read_text()
        import re
        strings=re.findall(r'"OK DQ [^"\n]*"',source)
        self.assertEqual(len(strings),2)
        audit=re.findall(r'"OK DQA [^"\n]*"',source)
        self.assertEqual(len(audit),1)
        for text in strings+audit:self.assertNotRegex(text,r'%[^% ]*[fFeEgGaA]')


if __name__=='__main__':unittest.main()
