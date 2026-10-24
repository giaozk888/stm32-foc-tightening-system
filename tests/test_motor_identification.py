"""No hardware: actual C owner, synthetic RL, malformed/unsafe evidence gates."""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from test_torque_chain import GCC, ROOT, FROZEN, function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import motor_identification_report as report


def rs_run(amps):
    return dict(mode='RS',status=3,fault=0,protection_evidence=proof(),rows=[dict(us=200000+k*6250,seq=1000+k*125,
        pending_before=999+k*125,id_ref=amps,iq_ref=0,id=amps,iq=0,
        vd=.1*amps+.002,vq=0,angle=6.28,speed=0) for k in range(32)])


def proof():
    return dict(verified=True,source='OFFLINE fixture only',fault=0,deadline_miss=0,ccr_late=0)


def l_run(mode,tau=.0004):
    rows=[];i=.05;dt=.00005;f=.3;rs=.1
    command=[.005 if k<4 else .01 for k in range(32)]
    for k in range(32):
        q=mode=='LQ'
        rows.append(dict(us=99800+k*50,seq=10000+k,pending_before=9999+k,
            id_ref=0 if q else .05 if k<4 else .1,
            iq_ref=(.05 if k<4 else .1) if q else 0,
            id=0 if q else i,iq=i if q else 0,
            vd=0 if q else command[k],vq=command[k] if q else 0,
            angle=1.2,speed=0))
        a=math.exp(-dt/tau);b=math.exp(-(1-f)*dt/tau)
        old=command[max(0,k-2)];new=command[max(0,k-1)]
        i=a*i+(b-a)*old/rs+(1-b)*new/rs
    return dict(mode=mode,status=3,fault=0,rows=rows,protection_evidence=proof(),latch_evidence=dict(
        verified=True,command_lag_cycles=2,sample_to_bottom_fraction=f,
        late_count=0,source='OFFLINE analytic two-segment PWM fixture, not board evidence'))


class MotorIdentTests(unittest.TestCase):
    def test_uart_decoder_complete_frozen_only_and_no_fake_timing_evidence(self):
        r=rs_run(.05);lines=['1 OK IDENT MODE=1 STATUS=3 REASON=0 N=32 USED=1']
        for k,row in enumerate(r['rows']):
            lines.append('2 OK MID K=%d US=%d SEQ=%d PSEQ=%d M=1 S=2 F=0 DR=50000 QR=0 D=50000 Q=0 VD=7000 VQ=0 A=6280000 RPM=0'%
                (k,row['us'],row['seq'],row['pending_before']))
        text='\n'.join(lines)
        out=report.decode_uart(text,'RS')
        self.assertAlmostEqual(out['rows'][0]['id'],.05)
        self.assertFalse(out['latch_evidence']['verified'])
        with self.assertRaises(report.Insufficient):report.decode_uart(text,'LQ')
        with self.assertRaises(report.Insufficient):report.decode_uart('\n'.join(lines[:-1]),'RS')
        with self.assertRaises(report.Insufficient):report.decode_uart(text+'\n1 OK IDENT MODE=1 STATUS=4 REASON=1 N=32','RS')

    def test_real_binding_manual_admission_busy_one_shot_and_no_power_writes(self):
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include "motor_identification.h"
typedef unsigned TickType_t;
#define CL_RUNNING 2
#define CL_READY 1
#define MOTOR_MODE_IDLE 0
#define DRIVER_SD_Pin 64
#define TIM_BDTR_MOE 0x8000
#define TIM_BDTR_AOE 0x4000
static struct {unsigned state,used;} cl_session={1,0};
static struct {unsigned ODR;} gpio;
static struct {unsigned BDTR,CCER;} tim;
#define TIM1 (&tim)
#define DRIVER_SD_GPIO_Port (&gpio)
static struct {unsigned source_seq;} cl_pwm_pending;
static struct {unsigned source_us;} cl_frame;
static unsigned critical,stops,tightening_start_request,tightening_stop_request;
static unsigned tightening_start_request_id,adc_fault,foc_fault,cl_seq,cl_outer_n;
static unsigned motor_control_mode,encoder_valid=1;
static float foc_id_ref_A,foc_iq_ref_A,foc_id_A,foc_iq_A,foc_vd_V,foc_vq_V;
static float encoder_position_deg,encoder_speed_rpm,encoder_theta_e;
static MotorIdentification motor_ident;
#define taskENTER_CRITICAL() (++critical)
#define taskEXIT_CRITICAL() (--critical)
#define PROTO_ERR_BUSY 1
#define pdMS_TO_TICKS(x) (x)
static unsigned Tightening_IsBusy(void){return 0;}
static unsigned ProtectedLoop_Ready(void){return 1;}
static void ProtectedLoop_Stop(void){++stops;cl_session.state=0;}
static unsigned LatestOriginal_Admit(void){return 0;}
static void MotorControl_SetIdle(void){motor_control_mode=0;}
static unsigned AS5047P_DmaNowUs(void){return 0;}
static unsigned xTaskGetTickCount(void){return 0;}
static void vTaskDelayUntil(TickType_t *w,unsigned t){(void)w;(void)t;}
static void UART_SendLiteral(const char *s){(void)s;}
static void Protocol_SendError(unsigned a,unsigned b,const char *s){(void)a;(void)b;(void)s;}
static void Protocol_SendFormatted(char *out,size_t n,const char *f,...){(void)out;(void)n;(void)f;}
#include "motor_identification_binding.inc"
int main(void){char out[320];
 (void)TighteningTask;(void)TighteningIntent_PrintStatus;(void)TighteningIntent_PrecheckOnly;
 assert(!MotorIdent_Command("START",out,sizeof out));
 gpio.ODR=64;
 assert(MotorIdent_Command("MOTOR TEST IDENT RS 50 LOCKED CONFIRM",out,sizeof out));
 assert(strstr(out,"ERR") && !motor_ident.used);
 gpio.ODR=0;
 MotorIdent_Command("MOTOR TEST IDENT RS 50 LOCKED CONFIRM",out,sizeof out);
 assert(motor_ident.used && motor_ident.status==MID_QUEUED && strstr(out,"OK"));
 MotorIdent_Command("MOTOR TEST IDENT RS 75 LOCKED CONFIRM",out,sizeof out);
 assert(strstr(out,"ERR") && motor_ident.current_a==.05f);
 motor_ident.status=MID_ACTIVE;cl_session.state=CL_RUNNING;
 MotorIdent_Command("MOTOR TEST IDENT ROW 0",out,sizeof out);assert(strstr(out,"ERR"));
 cl_seq=1;cl_frame.source_us=50;assert(MotorIdent_Ref(.05f,0));assert(foc_iq_ref_A==0);
 MotorIdent_Capture();
 encoder_speed_rpm=3;cl_seq=2;cl_frame.source_us=100;
 assert(!MotorIdent_Ref(.05f,0));assert(stops && motor_ident.status==MID_ABORT);
 assert(motor_ident.used && !critical);
 return 0;}
'''
        exe=ROOT/'tmp/motor-ident-binding.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-pedantic',
            '-UNDEBUG','-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
            input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        subprocess.run([str(exe)],check=True,capture_output=True)
        text=(ROOT/'firmware_common/motor_identification_binding.inc').read_text()
        self.assertNotIn('TIM1->CCR',text)
        self.assertNotIn('BSRR',text)
        # The only power operation is calling the ORIGINAL close/STOP path.
        self.assertNotIn('PowerStage_Enable',text)

    def test_actual_c_manual_table_waveform_duration_motion_limits_freeze(self):
        code=r'''
#include <assert.h>
#include "motor_identification.h"
int main(void){
 uint8_t m=0;float a=0,d=0,q=0;
 assert(!MotorIdent_Parse("START",&m,&a));
 assert(!MotorIdent_Parse("MOTOR TEST IDENT RS 150 LOCKED CONFIRM",&m,&a));
 assert(!MotorIdent_Parse("MOTOR TEST IDENT LQ CONFIRM",&m,&a));
 assert(MotorIdent_Parse("MOTOR TEST IDENT RS 75 LOCKED CONFIRM",&m,&a));
 assert(m==MID_RS && fabsf(a-.075f)<1e-6f);
 for(unsigned mode=MID_RS;mode<=MID_LQ;++mode){
  MotorIdentification s={.mode=mode,.status=MID_ACTIVE,.used=1,.current_a=.075f};
  for(unsigned k=1;k<8500 && s.status==MID_ACTIVE;++k){
   uint32_t us=k*50;
   if(!MotorIdent_Reference(&s,us,k,0,0,.05f,0,&d,&q))break;
   if(mode==MID_LQ){assert(d==0 && q<=.1f);}
   else {assert(q==0 && d<=.1f);}
   if(mode!=MID_RS && us<100000) assert(fabsf(d+q-.05f)<1e-6f);
   MotorIdentFrame r={.us=us,.seq=k,.id=.05f,.vd=.005f};
   assert(MotorIdent_Record(&s,r));
  }
  assert(s.status==MID_DONE && s.reason==MID_OK && s.used && s.count==32);
  MotorIdentFrame old=s.rows[0];
  assert(MotorIdent_Record(&s,(MotorIdentFrame){0}));
  assert(s.rows[0].seq==old.seq);
 }
 for(unsigned reason=0;reason<5;++reason){
  MotorIdentification s={.mode=MID_LQ,.status=MID_ACTIVE,.used=1};
  if(reason==0)assert(!MotorIdent_Reference(&s,50,1,.11f,0,0,0,&d,&q));
  if(reason==1)assert(!MotorIdent_Reference(&s,50,1,0,2.1f,0,0,&d,&q));
  if(reason==2)assert(!MotorIdent_Reference(&s,50,1,0,0,.201f,0,&d,&q));
  if(reason==3)assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f}));
  if(reason==4){
   assert(MotorIdent_Reference(&s,50,1,0,0,0,0,&d,&q));
   assert(!MotorIdent_Reference(&s,150,3,0,0,0,0,&d,&q));
  }
  assert(s.status==MID_ABORT && s.used);
 }
 return 0;
}'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('motor-ident-host'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
                input=code,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            subprocess.run([str(exe)],check=True,capture_output=True)

    def test_rs_bias_fit_ld_lq_and_pi_suggestions_no_write(self):
        data=dict(runs=[rs_run(x) for x in (.05,.075,.10)]+[l_run('LD'),l_run('LQ',.0005)])
        out=report.report(data,1000)
        self.assertFalse(out['errors'],out)
        self.assertAlmostEqual(out['rs']['rs_ohm'],.1)
        self.assertAlmostEqual(out['rs']['voltage_bias_v'],.002)
        self.assertLess(abs(out['ld']['inductance_h']-40e-6),1e-6)
        self.assertLess(abs(out['lq']['inductance_h']-50e-6),1e-6)
        self.assertAlmostEqual(out['pi_suggestion']['ki_d'],100)
        self.assertFalse(out['automatic_pi_write'])

    def test_bad_motion_fault_timing_axis_gap_noise_no_estimate(self):
        for mutate in (
            lambda r:r.update(fault=1),
            lambda r:r.update(status=4),
            lambda r:r['rows'][4].update(speed=3),
            lambda r:r['rows'][4].update(id=.4),
            lambda r:r['rows'][4].update(vq=.3),
            lambda r:r['rows'][4].update(angle=1.3),
            lambda r:r['rows'][4].update(seq=123),
            lambda r:r['rows'][4].update(pending_before=0),
            lambda r:r['latch_evidence'].update(verified=False),
            lambda r:r['latch_evidence'].update(command_lag_cycles=1),
            lambda r:r['latch_evidence'].update(late_count=1)):
            r=l_run('LD');mutate(r)
            with self.assertRaises(report.Insufficient):report.fit_l(r,.1)
        r=l_run('LD')
        for k,row in enumerate(r['rows']):row['id']+=.03*(-1 if k%2 else 1)
        with self.assertRaises(report.Insufficient):report.fit_l(r,.1)
        with self.assertRaises(report.Insufficient):report.fit_rs([rs_run(.05)])
        r=rs_run(.1)
        for row in r['rows']:row['iq']=.03
        with self.assertRaises(report.Insufficient):report.fit_rs([rs_run(.05),rs_run(.075),r])

    def test_normal_a_functions_pipeline_and_b_unchanged(self):
        old=expanded('a','Tightening240rpmFriction105OnCandidate')
        diag=expanded('a','MotorParameterIdentificationDiagnostic')
        # Diagnostic adds only two conditional hooks to the PI owner. Its PI,
        # transforms, SVPWM and order compare exactly after those hooks removed.
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate',
            'ProtectedLoop_Stop','ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage')):
            a=function(old,name);b=function(diag,name)
            if name=='FOC_CurrentLoopStep':
                b=b.replace('if (!MotorIdent_Ref(id_A,iq_A)) return;','').replace('MotorIdent_Capture();','')
            import re
            self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b),name)
        for path,sha in (
            ('foc2_app_a/build/Tightening240rpmFriction105OnCandidate/foc2.bin',
             '3adf71acf9579d455f9e0f27e27d121a863c570cde9f0baabb65b9f587ef2899'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
