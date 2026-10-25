"""Native diagnostic command/gain guards; normal BEMF arithmetic stays unchanged."""

from app_source_view import read_app_source
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_pi_compare as pi


class GainTests(unittest.TestCase):
    def test_real_current_pi_uniform_voltage_limit_and_anti_windup(self):
        code=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
#define FOC_BEMF_CANDIDATE 1
#define FOC_BEMF_GAIN_DIAG 1
#define FOC_BEMF_PSI_WB .00069732f
#define FOC_CURRENT_PI_IDENTIFIED_ENABLE 1
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
static void ProtectedLoop_EmergencyOff(unsigned x){faults=x;}
static float ClampFloat(float x,float lo,float hi){return x<lo?lo:x>hi?hi:x;}
static unsigned char bemf_enabled;
static uint32_t bemf_gain_percent;
static float encoder_omega_e_rad_s;
static FocBemfFrame bemf_frame;
static unsigned injected_seq_count;
static struct {unsigned source_us;} cl_frame;
static void step(float *state,unsigned on,unsigned gain,float omega,float *out){
float foc_id_ref_A=.25f,foc_iq_ref_A=.25f,id_A=.25f,iq_A=.25f;
float foc_int_d_V=state[0],foc_int_q_V=state[1];
float vd,vq,err_d,err_q,mag2,limit2;
bemf_enabled=(unsigned char)on;bemf_gain_percent=gain;encoder_omega_e_rad_s=omega;
injected_seq_count++;cl_frame.source_us=injected_seq_count*50;
''' + pi.pi_source() + r'''
state[0]=foc_int_d_V;state[1]=foc_int_q_V;
out[0]=vd;out[1]=vq;out[2]=bemf_frame.vq_ff;out[3]=(float)bemf_frame.saturated;
}
int main(void){
float off[2]={.01f,-.02f},zero[2]={.01f,-.02f},a[4],b[4];
for(unsigned i=0;i<350;i++){
 step(off,0,100,250,a);step(zero,1,0,250,b);
 assert(!memcmp(off,zero,sizeof off) && !memcmp(a,b,sizeof a));
}
unsigned gains[]={25,50,75,100};
for(unsigned k=0;k<4;k++){
 float state[2]={.01f,-.02f};
 step(state,1,gains[k],251.327412f,a);
 assert(!faults && a[3]==0 && fabsf(a[2]-251.327412f*.00069732f*(float)gains[k]*.01f)<1e-7f);
 step(state,1,gains[k],100000.f,a);
 assert(a[3]==1 && fabsf(sqrtf(a[0]*a[0]+a[1]*a[1])-1.6f)<1e-6f);
 assert(fabsf(state[0]-ClampFloat(a[0],-.75f,.75f))<1e-6f);
 assert(fabsf(state[1]-ClampFloat(a[1]-a[2],-.75f,.75f))<1e-6f);
}
float state[2]={0};step(state,1,101,250,a);assert(faults==CL_BAD_OUTPUT);
return 0;}
'''
        exe=ROOT/'tmp/bemf-flux-gain-pi-host.exe'
        p=subprocess.run([str(pi.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-Wno-unused-variable','-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
            input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_native_gain_and_command_guards(self):
        code=r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#define FOC_BEMF_GAIN_DIAG 1
#define FOC_BEMF_PSI_WB .00069732f
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
static unsigned bemf_gain_percent;
static FocBemfFrame bemf_frame;
#include "foc_bemf_feedforward_binding.inc"
int main(void){char out[384],cmd[80];float q,base;
unsigned gains[]={0,25,50,75,100};
for(unsigned i=0;i<5;i++){
 unsigned g=gains[i];snprintf(cmd,sizeof cmd,"MOTOR TEST BEMF GAIN %u",g);
 assert(Bemf_Command(cmd,out,sizeof out) && !mask);
 assert(bemf_gain_percent==g && !bemf_enabled && !bemf_frame.valid);
 assert(strstr(out,"GAIN_PCT=") && strstr(out,"EFFECTIVE_PSI_NWB="));
 for(int k=-1;k<=1;k++){
  float w=(float)k*251.327412f;
  assert(FocBemfGain_Apply(1,w,g,&q));
  assert(fabsf(q-w*.00069732f*(float)g*.01f)<1e-7f);
 }
}
FocBemf_Apply(1,251.327412f,&base);
assert(FocBemfGain_Apply(1,251.327412f,100,&q) && q==base);
assert(FocBemfGain_Apply(0,NAN,999,&q) && q==0);
assert(!FocBemfGain_Apply(1,1,101,&q) && q==0);
assert(!FocBemfGain_Apply(1,INFINITY,25,&q));
assert(FocBemfGain_Apply(1,NAN,0,&q) && q==0);
const char *bad[]={"-1","101","125","25junk","25.0"," 25","25 ","4294967296"};
for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++){
 snprintf(cmd,sizeof cmd,"MOTOR TEST BEMF GAIN %s",bad[i]);
 assert(Bemf_Command(cmd,out,sizeof out));
 assert(strstr(out,"ERR BEMF GAIN_RANGE") && bemf_gain_percent==100);
}
unsigned *blockers[]={&cl_session.state,&busy,&tightening_start_request,
 &tightening_stop_request,&motor_control_mode,&gpio.ODR,&tim.BDTR,&tim.CCER};
for(unsigned k=0;k<sizeof blockers/sizeof blockers[0];k++){
 *blockers[k]=k==0?CL_RUNNING:k==5?DRIVER_SD_Pin:k==6?TIM_BDTR_MOE:1;
 assert(Bemf_Command("MOTOR TEST BEMF GAIN 25",out,sizeof out));
 assert(strstr(out,"ERR BEMF BUSY") && bemf_gain_percent==100 && !mask);
 *blockers[k]=0;
}
assert(Bemf_Command("MOTOR TEST BEMF ON",out,sizeof out) && bemf_enabled);
assert(Bemf_Command("MOTOR TEST BEMF GAIN 25",out,sizeof out) && bemf_enabled);
assert(Bemf_Command("MOTOR TEST BEMF OFF",out,sizeof out) && !bemf_enabled);
assert(bemf_gain_percent==25 && !tim.BDTR && !tim.CCER && !gpio.ODR);
mask=1;Bemf_Command("MOTOR TEST BEMF GAIN 50",out,sizeof out);assert(mask==1);
return 0;}
'''
        exe=ROOT/'tmp/bemf-flux-gain-host.exe'
        p=subprocess.run([str(pi.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
            input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_formal_b_not_enabled(self):
        self.assertNotIn('FOC_BEMF_GAIN_DIAG',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        main=read_app_source(ROOT/'foc2_app_a/Core/Src/main.c')
        self.assertIn('static volatile uint32_t bemf_gain_percent=0U;',main)
        self.assertLess(main.index('FocBemfGain_Apply(bemf_on'),
                        main.index('mag2 = vd * vd',main.index('FocBemfGain_Apply(bemf_on')))


if __name__=='__main__':unittest.main()
