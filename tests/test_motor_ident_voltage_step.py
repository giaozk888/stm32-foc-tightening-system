"""Exclusive voltage diagnostic: zero current PI dynamics, original safeguards."""
import re
import sys
import unittest
from test_motor_ident_timing import TimingTests
from test_motor_ident_rs_reject_count import DEFINES
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded

VDEFS=DEFINES+'\n#define FOC_IDENT_L_RS_ADMISSION_ENABLE 1\n#define FOC_IDENT_VOLTAGE_STEP_DIAG 1\n'


class VoltageStepTests(unittest.TestCase):
    def test_real_c_manual_waveform_neutral_duration_and_frozen_end(self):
        TimingTests().compile_run(VDEFS+r'''
#include <assert.h>
#include "motor_identification.h"
int main(void){uint8_t mode=0;float amps=9,d=0,q=0,vd=9,vq=9;
 assert(sizeof(MotorIdentFrame)==48 && sizeof(MotorIdentification)==1740);
 assert(!MotorIdent_Parse("MOTOR TEST IDENT RS 50 LOCKED CONFIRM",&mode,&amps));
 assert(!MotorIdent_Parse("MOTOR TEST IDENT LD RS_VALIDATED LOCKED CONFIRM",&mode,&amps));
 assert(!MotorIdent_Parse("MOTOR TEST IDENT LDV 100MV LOCKED CONFIRM",&mode,&amps));
 assert(MotorIdent_Parse("MOTOR TEST IDENT LDV 50MV LOCKED CONFIRM",&mode,&amps));
 assert(mode==MID_LD && amps==0);
 assert(MotorIdent_Parse("MOTOR TEST IDENT LQV 50MV LOCKED CONFIRM",&mode,&amps));
 assert(mode==MID_LQ && amps==0);
 for(unsigned m=MID_LD;m<=MID_LQ;++m){
  MotorIdentification s={.mode=m,.status=MID_ACTIVE,.used=1};
  for(unsigned k=1;k<=2080;++k){unsigned us=k*50;
   unsigned ok=MotorIdent_Reference(&s,us,k,0,0,.05f,0,&d,&q);
   assert(d==0 && q==0);
   MotorIdent_Voltage(&s,us,&vd,&vq);
   if(us==104000){assert(!ok && s.status==MID_DONE && vd==0 && vq==0);break;}
   assert(ok);
   if(us<100000)assert(vd==0 && vq==0);
   else if(m==MID_LD)assert(fabsf(vd-.05f)<1e-7f && vq==0);
   else assert(fabsf(vq-.05f)<1e-7f && vd==0);
   assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=us,.seq=k,.id=.05f,
       .vd=vd,.vq=vq,.raw_u=1500,.raw_v=1501}));
  }
  assert(s.count==32 && s.used);MotorIdent_Voltage(&s,100100,&vd,&vq);assert(vd==0 && vq==0);
  assert(s.rows[0].raw_u==1500 && s.rows[31].raw_v==1501);
 }
 for(unsigned st=MID_IDLE;st<=MID_ABORT;++st){
  if(st==MID_ACTIVE)continue;
  MotorIdentification s={.status=st,.mode=MID_LQ};
  MotorIdent_Voltage(&s,100100,&vd,&vq);assert(vd==0 && vq==0);
 }
 return 0;}
''','voltage-step-waveform')

    def test_no_pi_in_exclusive_expansion_and_all_other_math_frozen(self):
        old=expanded('a','MotorParameterIdentificationLAdmissionDiagnostic')
        new=expanded('a','MotorParameterIdentificationVoltageStepDiagnostic')
        for name in set(FROZEN+('FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
            'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_Pair')):
            if name=='FOC_CurrentLoopStep':continue  # Only the explicit PI bypass is intentional.
            self.assertEqual(re.sub(r'\s+','',function(old,name)),re.sub(r'\s+','',function(new,name)),name)
        body=function(new,'FOC_CurrentLoopStep')
        self.assertIn('MotorIdent_Voltage(&motor_ident,cl_frame.source_us,&vd,&vq)',body)
        self.assertNotIn('foc_int_d_V +=',body);self.assertNotIn('foc_int_q_V +=',body)
        self.assertNotIn('FOC_CURRENT_KP_V_PER_A * err_d',body)
        suffix='v_alpha=vd*c-vq*s;'
        self.assertEqual(re.sub(r'\s+','',function(old,'FOC_CurrentLoopStep')).split(suffix)[1],
                         re.sub(r'\s+','',body).split(suffix)[1])

    def test_original_safety_and_reject_data_never_in_trace(self):
        TimingTests().compile_run(VDEFS+r'''
#include <assert.h>
#include "motor_identification.h"
int main(void){float d=0,q=0,vd=0,vq=0;
 MotorIdentification s={.mode=MID_LD,.status=MID_ACTIVE};
 assert(!MotorIdent_Reference(&s,50,1,0,3,.01f,0,&d,&q));assert(s.reason==MID_MOTION);
 MotorIdent_Voltage(&s,100100,&vd,&vq);assert(vd==0 && vq==0);
 s=(MotorIdentification){.mode=MID_LQ,.status=MID_ACTIVE};
 assert(!MotorIdent_Reference(&s,50,1,0,0,NAN,0,&d,&q));assert(s.reason==MID_BAD_DATA);
 s=(MotorIdentification){.mode=MID_LD,.status=MID_ACTIVE};
 assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f}));assert(s.reason==MID_VOLTAGE);
 s=(MotorIdentification){.mode=MID_LD,.status=MID_ACTIVE};
 assert(MotorIdent_Reference(&s,100050,1,0,0,.21f,0,&d,&q));
 assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=100050,.id=.21f,.vd=.05f}));
 assert(!s.count && s.current_reject_count==1); /* Estimator reject is not fake current. */
 return 0;}
''','voltage-step-safety')


if __name__=='__main__':unittest.main()
