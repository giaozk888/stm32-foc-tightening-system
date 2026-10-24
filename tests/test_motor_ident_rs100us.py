"""Rs-only software dt upper limit: inclusive 100us, L remains 55us."""
import hashlib
import re
import struct
import unittest
import test_motor_ident_timing as timing
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded
import motor_ident_timing_report as report


class Rs100usTests(unittest.TestCase):
    def test_actual_c_boundaries_original57us_replay_and_hold_evidence(self):
        timing.TimingTests().compile_run(r'''
#include <assert.h>
#define FOC_IDENT_TIMING_TRACE_ENABLE 1
#define FOC_IDENT_CURRENT_REJECT_ENABLE 1
#define FOC_IDENT_RS_GAP_ADMISSION_ENABLE 1
#define MID_RS_SOFT_DT_MAX_US 100U
#include "motor_identification.h"
int main(void){float d=0,q=0;
 for(unsigned mode=MID_RS;mode<=MID_LQ;++mode)
 for(unsigned dt=44;dt<=101;++dt){
  MotorIdentification s={.mode=mode,.status=MID_ACTIVE,.current_a=.05f,
      .start_us=7992290,.last_seq=157480,.last_us=7992295};
  unsigned ok=MotorIdent_Reference(&s,7992295+dt,157481,0,0,.05f,0,&d,&q);
  assert(ok==(dt>=45 && dt<=(mode==MID_RS?100:55)));
  if(!ok){assert(s.reason==MID_TIMING && s.timing_failure.valid);
   assert(s.timing_failure.delta_seq==1 && s.timing_failure.delta_us==dt);
   assert(s.timing_failure.flags==(dt<45?2:4));assert(d==0 && q==0);
  }
 }
 /* User changed sequential-frame software upper bound only.
  * A seq gap still needs exact hold evidence, original scaled 55us bound. */
 for(unsigned dt=100;dt<=200;dt+=10){
  MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
      .last_seq=10,.last_us=100,.rs_hold_delta=1};
  assert(MotorIdent_Reference(&s,100+dt,12,0,0,.05f,0,&d,&q)==(dt<=110));
 }
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
      .last_seq=10,.last_us=100};
 assert(!MotorIdent_Reference(&s,200,12,0,0,.05f,0,&d,&q));
 assert(s.reason==MID_TIMING && s.timing_failure.flags==1); /* unexplained seq gap */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,400000,8000,0,0,.05f,0,&d,&q));
 assert(s.status==MID_DONE); /* Fixed overall duration unchanged. */
 return 0;}
''','motor-ident-rs100us')

    def test_policy_uart_and_real_binding(self):
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        code='#define MID_RS_SOFT_DT_MAX_US 100U\n'+text[start:text.index("'''",start)]
        code=code.replace('encoder_speed_rpm=3;cl_seq=2;cl_frame.source_us=100;',r'''
 cl_seq=2;cl_frame.source_us=107;assert(MotorIdent_Ref(.05f,0));assert(!stops);
 MotorIdent_Command("MOTOR TEST IDENT TIME POLICY",out,sizeof out);
 assert(strstr(out,"RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55"));
 encoder_speed_rpm=3;cl_seq=3;cl_frame.source_us=157;
''')
        timing.TimingTests().compile_run(code,'motor-ident-rs100us-binding')

    def test_decoder_requires_explicit_image_policy(self):
        raw=bytearray(1724)
        struct.pack_into('<15I',raw,1660,10,100,11,201,1,101,4,1,11,11,201,0,0,1,1)
        result=report.decode(raw,max_dt_us=100)
        self.assertEqual(result['failed_conditions'],['software_dt_above_100us'])
        # At 100us only unexplained sequence change can fail; not a dt error.
        struct.pack_into('<15I',raw,1660,10,100,12,200,2,100,1,1,12,12,200,0,0,1,1)
        self.assertEqual(report.decode(raw,max_dt_us=100)['failed_conditions'],['sequence_delta_not_1'])
        with self.assertRaises(ValueError):report.decode(raw)  # historical 55 policy cannot decode new flags

    def test_frozen_control_original_images_and_explicit_preset(self):
        a=expanded('a','MotorParameterIdentificationRsGapDiagnostic')
        b=expanded('a','MotorParameterIdentificationRs100usDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationRsGapDiagnostic/foc2.bin',
             '9f0bf902af96699fde1d817b486588a228b71e830a291ffb49cf5f015f220676'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
