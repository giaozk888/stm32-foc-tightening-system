"""Actual current-loop insertion, coherent console, disabled-path isolation."""
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
from test_torque_chain import function
from test_torque350_five_second import expanded


class BemfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'tmp/bemf-host';cls.out.mkdir(exist_ok=True)
        cls.libs=[]
        for name,feature,psi in (('baseline',False,'0.0'),('ready',True,'0.0001'),('unset',True,'0.0')):
            code=r'''
#include <math.h>
#include <stdint.h>
#include "foc_bemf_feedforward.h"
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
static unsigned char bemf_enabled;
static float encoder_omega_e_rad_s;
static FocBemfFrame bemf_frame;
static unsigned injected_seq_count;
static struct {unsigned source_us;} cl_frame;
__declspec(dllexport) unsigned apply(unsigned on,float w,float *v) {
return FocBemf_Apply((uint8_t)on,w,v);}
__declspec(dllexport) unsigned failed(void) {return faults;}
__declspec(dllexport) void step(float *state,float ref_d,float ref_q,
float id_A,float iq_A,float omega,unsigned on,float *out) {
float foc_id_ref_A=ref_d,foc_iq_ref_A=ref_q;
float foc_int_d_V=state[0],foc_int_q_V=state[1];
float vd,vq,err_d,err_q,mag2,limit2;
bemf_enabled=(unsigned char)on;encoder_omega_e_rad_s=omega;
injected_seq_count++;cl_frame.source_us=injected_seq_count*50;
''' + pi.pi_source() + r'''
state[0]=foc_int_d_V;state[1]=foc_int_q_V;
out[0]=vd;out[1]=vq;out[2]=bemf_frame.vq_ff;
out[3]=(float)bemf_frame.saturated;out[4]=(float)bemf_frame.seq;
}
'''
            dll=cls.out/(name+'.dll')
            p=subprocess.run([str(pi.GCC),'-std=c11','-O2','-shared','-Wall','-Wextra',
                '-Werror','-Wno-unused-function','-Wno-unused-variable',
                '-DFOC_CURRENT_PI_IDENTIFIED_ENABLE=1',f'-DFOC_BEMF_PSI_WB={psi}f',
                *(['-DFOC_BEMF_CANDIDATE=1'] if feature else []),
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(dll)],
                input=code,text=True,capture_output=True)
            if p.returncode:raise RuntimeError(p.stdout+p.stderr)
            lib=ct.CDLL(str(dll));cls.libs.append(lib)
            lib.step.argtypes=[ct.POINTER(ct.c_float)]+[ct.c_float]*5+[ct.c_uint,ct.POINTER(ct.c_float)]
            lib.step.restype=None
            lib.apply.argtypes=[ct.c_uint,ct.c_float,ct.POINTER(ct.c_float)]
            lib.apply.restype=ct.c_uint
            lib.failed.restype=ct.c_uint

    def test_signed_rad_s_zero_reverse_no_pole_pair_double_count(self):
        out=ct.c_float()
        for w in (-314.159265,-251.327412,0.,251.327412,314.159265):
            self.assertEqual(self.libs[1].apply(1,w,ct.byref(out)),1)
            self.assertAlmostEqual(out.value,w*.0001,places=8)

    def test_no_flux_no_enable_and_nonfinite_is_not_injected(self):
        out=ct.c_float(123)
        self.assertEqual(self.libs[2].apply(1,1,ct.byref(out)),0)
        self.assertEqual(out.value,0)
        for w in (float('nan'),float('inf'),-float('inf')):
            self.assertEqual(self.libs[1].apply(1,w,ct.byref(out)),0)
            self.assertEqual(out.value,0)
            self.assertEqual(self.libs[1].apply(0,w,ct.byref(out)),1)
            self.assertEqual(out.value,0)
        state=(ct.c_float*2)();o=(ct.c_float*5)()
        self.libs[2].step(state,0,.1,0,0,10,1,o)
        self.assertEqual(self.libs[2].failed(),16)

    def test_off_is_bitwise_original_pi_for_350_updates(self):
        states=[(ct.c_float*2)(),(ct.c_float*2)()]
        for k in range(350):
            results=[]
            for lib,state in zip(self.libs[:2],states):
                o=(ct.c_float*5)()
                lib.step(state,-.3 if k%2 else .1,.5,-.1,.1,250,0,o)
                results.append(bytes(state)+bytes(o)[:8])
            self.assertEqual(*results)

    def test_unsaturated_addition_uses_measured_speed(self):
        s=(ct.c_float*2)();o=(ct.c_float*5)()
        self.libs[1].step(s,.1,.4,.05,.2,251.327412,1,o)
        self.assertEqual(o[3],0)
        self.assertAlmostEqual(o[0],.0377556644*.05+s[0],places=7)
        self.assertAlmostEqual(o[1],.0210738052*.2+s[1]+o[2],places=7)
        self.assertAlmostEqual(o[2],.0251327412,places=8)

    def test_common_vector_limit_and_pi_only_anti_windup(self):
        for w in (-100000,100000):
            s=(ct.c_float*2)(.01,-.02);o=(ct.c_float*5)()
            self.libs[1].step(s,.25,.25,.25,.25,w,1,o)
            self.assertEqual(o[3],1)
            self.assertAlmostEqual((o[0]**2+o[1]**2)**.5,1.6,places=6)
            self.assertAlmostEqual(s[0],max(-.75,min(.75,o[0])),places=6)
            self.assertAlmostEqual(s[1],max(-.75,min(.75,o[1]-o[2])),places=6)

    def test_real_console_guard_unconfigured_and_no_output_side_effects(self):
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "foc_bemf_feedforward.h"
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
static unsigned char bemf_enabled;
static FocBemfFrame bemf_frame;
#include "foc_bemf_feedforward_binding.inc"
int main(void){char out[384];
assert(!Bemf_Command("MOTOR TEST DQ STATUS",out,sizeof out));
assert(Bemf_Command("MOTOR TEST BEMF ON",out,sizeof out));
assert(!mask);
if (!FocBemf_Configured()) {
 assert(!bemf_enabled && strstr(out,"UNCALIBRATED_PSI"));return 0;
}
assert(bemf_enabled && !bemf_frame.valid);
unsigned *blockers[]={&cl_session.state,&busy,&tightening_start_request,
 &tightening_stop_request,&motor_control_mode,&gpio.ODR,&tim.BDTR,&tim.CCER};
for(unsigned k=0;k<sizeof blockers/sizeof blockers[0];k++){
 *blockers[k]=k==0?CL_RUNNING:k==5?DRIVER_SD_Pin:k==6?TIM_BDTR_MOE:1;
 assert(Bemf_Command("MOTOR TEST BEMF OFF",out,sizeof out));
 assert(strstr(out,"ERR BEMF BUSY") && bemf_enabled && !mask);
 *blockers[k]=0;
}
assert(Bemf_Command("MOTOR TEST BEMF OFF",out,sizeof out));
assert(!bemf_enabled && !mask);
assert(Bemf_Command("MOTOR TEST BEMF STATUS",out,sizeof out));
assert(strstr(out,"CONFIGURED=1") && strstr(out,"PSI_NWB=100000") && strstr(out,"DQ_CROSS=0"));
bemf_frame=(FocBemfFrame){.seq=123,.source_us=6150,.valid=1,.vq_ff=.025f,.omega_e=250};
assert(Bemf_Command("MOTOR TEST BEMF VOLTAGE",out,sizeof out));
assert(strstr(out,"SEQ=123") && strstr(out,"US=6150") && strstr(out,"VQ_FF_UV=25000"));
assert(BemfWire_Scaled(NAN,1e6f)==INT32_MIN);
assert(Bemf_Command("MOTOR TEST BEMF UNKNOWN",out,sizeof out));
assert(strstr(out,"ERR BEMF COMMAND"));
return 0;}
'''
        for val in ('0.0','0.0001'):
            exe=self.out/('console'+val+'.exe')
            p=subprocess.run([str(pi.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror',
                f'-DFOC_BEMF_PSI_WB={val}f','-I',str(ROOT/'firmware_common'),
                '-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_frozen_control_pipeline_irqs_b_and_default_dq_disabled(self):
        before=expanded('a','DqOriginalRuntime');after=expanded('a','BemfFeedforwardCandidate')
        for name in ('FOC_EncoderSpeedUpdate','Encoder_ElectricalAngleRad',
                     'ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty','ProtectedLoop_TimerHealthy',
                     'ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','PowerStage_Enable',
                     'PowerStage_Disable','TighteningTask','MotorControl_SetIq'):
            self.assertEqual(function(before,name),function(after,name),name)
        f=function(after,'FOC_CurrentLoopStep')
        self.assertNotIn('FocDqDecoupling_Apply',f)
        self.assertLess(f.index('FocBemf_Apply'),f.index('mag2 = vd * vd'))
        self.assertNotIn('printf',f)
        self.assertNotIn('snprintf',f)
        # Already-existing images (not rebuilt or written to the device).
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build/DqOriginalRuntime/foc2.bin').read_bytes()).hexdigest(),
            '95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e')
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')
        self.assertNotIn('FOC_BEMF',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        p=next(p for p in presets['configurePresets'] if p['name']=='BemfFeedforwardCandidate')
        self.assertEqual(p['cacheVariables']['FOC_BEMF_PSI_WB'],'0.0')
        self.assertEqual(p['cacheVariables']['FOC_DQ_DECOUPLING_CANDIDATE'],'OFF')
        self.assertEqual(p['cacheVariables']['FOC_BEMF_ENABLED_DEFAULT'],'OFF')

    def test_cmake_rejects_uncalibrated_boot_enable_dq_and_nan(self):
        cases=(('BemfRejectedUncalibrated',['-DFOC_BEMF_ENABLED_DEFAULT=ON'],'Cannot enable BEMF'),
               ('BemfRejectedDq',['-DFOC_DQ_DECOUPLING_CANDIDATE=ON'],'excludes dq'),
               ('BemfRejectedFlux',['-DFOC_BEMF_PSI_WB=nan'],'PSI must'))
        for name,args,message in cases:
            p=subprocess.run(['cmake','--preset','BemfFeedforwardCandidate',
                '-B','build/'+name]+args,cwd=ROOT/'foc2_app_a',
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            self.assertNotEqual(p.returncode,0,p.stdout)
            self.assertIn(message,p.stdout)


if __name__=='__main__':unittest.main()
