"""Rs cumulative reject no longer stops; continuous/safety/time limits remain."""
import hashlib
import unittest
import re
import test_motor_ident_timing as timing
import test_motor_identification as fixtures
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded
import motor_identification_report as report


class RsRejectOnlyTests(unittest.TestCase):
    def test_real_c_total_counter_not_stop_but_run_and_l_still_stop(self):
        timing.TimingTests().compile_run(r'''
#include <assert.h>
#define FOC_IDENT_CURRENT_REJECT_ENABLE 1
#define FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT 1
#include "motor_identification.h"
int main(void){float d=0,q=0;
 for(unsigned mode=MID_RS;mode<=MID_LQ;++mode){
  MotorIdentification s={.mode=mode,.status=MID_ACTIVE,.current_a=.05f};
  for(unsigned k=1;k<=33;++k){
   unsigned ok=MotorIdent_Reference(&s,k*50,k,0,0,k%2?.21f:.05f,0,&d,&q);
   assert(ok==(mode==MID_RS || k<33));
  }
  assert(s.current_reject_count==17 && s.max_current_reject_run==1);
  if(mode==MID_RS){assert(s.status==MID_ACTIVE && d==.05f && q==0);}
  else assert(s.reason==MID_CURRENT && s.status==MID_ABORT && d==0 && q==0);
 }
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 for(unsigned k=1;k<=3;++k)
  assert(MotorIdent_Reference(&s,k*50,k,0,0,.05f,.21f,&d,&q)==(k<3));
 assert(s.reason==MID_CURRENT && s.max_current_reject_run==3 && d==0 && q==0);
 /* Many isolated rejected measurements: fixed lease, accepted-only window. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 for(unsigned k=1;k<=8000;++k){
  float sample=k%2?.21f:.05f;
  unsigned ok=MotorIdent_Reference(&s,k*50,k,0,0,sample,0,&d,&q);
  if(!ok){assert(k==8000 && s.status==MID_DONE);break;}
  assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=k*50,.seq=k,.id=sample,.vd=.005f}));
 }
 assert(s.current_reject_count>16 && s.max_current_reject_run==1 && s.count==32);
 for(unsigned k=0;k<s.count;++k)assert(s.rows[k].id==.05f && s.rows[k].seq%2==0);
 assert(d==0 && q==0);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(MotorIdent_Reference(&s,50,1,0,0,.21f,0,&d,&q));
 assert(!MotorIdent_Record(&s,(MotorIdentFrame){.id=.21f,.vd=.201f}));
 assert(s.reason==MID_VOLTAGE); /* Rejection cannot swallow voltage stop. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,50,1,0,2.01f,.21f,0,&d,&q));assert(s.reason==MID_MOTION);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,50,1,NAN,0,.21f,0,&d,&q));assert(s.reason==MID_BAD_DATA);
 return 0;}
''','motor-ident-rs-reject-only')

    def test_real_binding_counts_and_explicit_policy(self):
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        code=('#define FOC_IDENT_CURRENT_REJECT_ENABLE 1\n'
              '#define FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT 1\n#define __DMB() ((void)0)\n'+
              text[start:text.index("'''",start)])
        code=code.replace('struct {unsigned source_us;} cl_frame;',
                          'struct {unsigned source_us; unsigned short u,v;} cl_frame;')
        code=code.replace('encoder_speed_rpm=3;cl_seq=2;cl_frame.source_us=100;',r'''
 for(unsigned k=2;k<=35;++k){
  cl_seq=k;cl_frame.source_us=k*50;
  assert(MotorIdent_Ref(k%2?.05f:.21f,0));
 }
 assert(!stops && motor_ident.current_reject_count==17 && motor_ident.status==MID_ACTIVE);
 encoder_speed_rpm=3;cl_seq=36;cl_frame.source_us=1800;
''')
        code=code.replace('assert(motor_ident.used && !critical);',r'''
 assert(motor_ident.used && !critical);
 MotorIdent_Command("MOTOR TEST IDENT REJECT",out,sizeof out);
 assert(strstr(out,"REJECT=17") && strstr(out,"REJECT_MAX=0 RUN_LIMIT=3 FIRST=1 TOTAL_STOP=0"));
''')
        timing.TimingTests().compile_run(code,'motor-ident-rs-reject-only-binding')

    def test_estimator_explicit_policy_good_only_and_insufficient_data(self):
        runs=[fixtures.rs_run(a) for a in (.05,.075,.1)]
        policy=dict(REJECT=17,GOOD=701,MAX_RUN=1,REJECT_MAX=0,RUN_LIMIT=3,TOTAL_STOP=0)
        for r in runs:r['current_admission']=policy.copy()
        self.assertAlmostEqual(report.fit_rs(runs)['rs_ohm'],.1)
        # Old data cannot silently opt into relaxed Rs policy by raising count.
        r=fixtures.rs_run(.05)
        r['current_admission']=dict(REJECT=17,GOOD=701,MAX_RUN=1,REJECT_MAX=16,RUN_LIMIT=3)
        with self.assertRaises(report.Insufficient):report.guard(r)
        for mode in ('LD','LQ'):
            r=fixtures.l_run(mode);r['current_admission']=policy.copy()
            with self.assertRaises(report.Insufficient):report.guard(r)
        for mutate in (dict(MAX_RUN=3),dict(REJECT_MAX=16),dict(TOTAL_STOP=2),dict(GOOD=1)):
            r=fixtures.rs_run(.05);r['current_admission']={**policy,**mutate}
            with self.assertRaises(report.Insufficient):report.guard(r)
        r=fixtures.rs_run(.05);r['current_admission']=policy.copy();r['rows']=r['rows'][:16]
        with self.assertRaises(report.Insufficient):report.guard(r)
        r=fixtures.rs_run(.05);r['current_admission']=policy.copy();r['rows'][3]['id']=.3
        with self.assertRaises(report.Insufficient):report.guard(r)

    def test_frozen_control_and_old_image_pins(self):
        a=expanded('a','MotorParameterIdentificationRs100usDiagnostic')
        b=expanded('a','MotorParameterIdentificationRsRejectOnlyDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationRs100usDiagnostic/foc2.bin',
             '3f38586c511f688da8b66862d9a27ea8dce11b9c4b869f7bdc526a53bc1bae3e'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
