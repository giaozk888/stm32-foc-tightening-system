"""Rs bounded held-frame admission; L strictness and controller stay frozen."""
import hashlib
import json
import struct
import subprocess
import sys
import unittest
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded
import test_motor_ident_timing as timing
import test_motor_identification as fixtures
sys.path.insert(0,str(ROOT/'tools'))
import motor_identification_report as report


class RsGapTests(unittest.TestCase):
    def test_real_c_gap_evidence_budgets_ld_lq_duration_and_rejects(self):
        code=r'''
#include <assert.h>
#include <stddef.h>
#define FOC_IDENT_CURRENT_REJECT_ENABLE 1
#define FOC_IDENT_TIMING_TRACE_ENABLE 1
#define FOC_IDENT_RS_GAP_ADMISSION_ENABLE 1
#define MID_TRAVEL_EXIT_ENABLE 0
#include "motor_identification.h"
int main(void){float d=0,q=0;
 assert(sizeof(MotorIdentification)==1740);
 assert(offsetof(MotorIdentification,rs_hold_delta)==1724);
 /* Same seq/us as actual frozen failing frame: one discriminator hold. */
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
   .start_us=7978299,.last_seq=157402,.last_us=7988404,.rs_hold_delta=1};
 assert(MotorIdent_Reference(&s,7988504,157404,0,0,.05f,0,&d,&q));
 assert(s.rs_skipped_pairs==1 && s.rs_gap_events==1 && !s.timing_failure.valid);
 assert(s.last_seq==157404 && s.last_us==7988504 && d==.05f && q==0);
 for(unsigned mode=MID_RS;mode<=MID_LQ;++mode)
 for(unsigned ds=1;ds<=4;++ds)for(unsigned hold=0;hold<=3;++hold)
 for(unsigned dt=40;dt<=225;dt+=5){
  s=(MotorIdentification){.mode=mode,.status=MID_ACTIVE,.current_a=.05f,
     .last_us=100,.last_seq=10,.rs_hold_delta=hold};
  unsigned allowed=(ds==1 && dt>=45 && dt<=55) ||
     (mode==MID_RS && ds>=2 && ds<=3 && hold==ds-1 && dt>=45*ds && dt<=55*ds);
  unsigned ok=MotorIdent_Reference(&s,100+dt,10+ds,0,0,.05f,0,&d,&q);
  assert(ok==allowed);
  if(!allowed)assert(s.reason==MID_TIMING && s.timing_failure.valid);
 }
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
    .last_us=100,.last_seq=10,.rs_hold_delta=1};
 for(unsigned k=1;k<=17;++k){
  unsigned ok=MotorIdent_Reference(&s,100+100*k,10+2*k,0,0,.05f,0,&d,&q);
  assert(ok==(k<=16));
 }
 assert(s.rs_skipped_pairs==16 && s.rs_gap_events==16 && s.rs_max_skipped==1);
 assert(s.reason==MID_TIMING && s.timing_failure.delta_seq==2 && d==0 && q==0);
 /* Accepted-frame estimator has no synthetic sample, reject still excluded. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
   .last_us=199950,.last_seq=3999,.rs_hold_delta=1};
 assert(MotorIdent_Reference(&s,200050,4001,0,0,.21f,0,&d,&q));
 assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=200050,.seq=4001,.id=.21f,.vd=.01f}));
 assert(!s.count && s.current_reject_count==1 && s.rs_skipped_pairs==1);
 s.rs_hold_delta=0;
 assert(MotorIdent_Reference(&s,200100,4002,0,0,.05f,0,&d,&q));
 assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=200100,.seq=4002,.id=.05f,.vd=.005f}));
 assert(s.count==1 && s.rows[0].seq==4002 && s.rows[0].id==.05f);
 assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f}));assert(s.reason==MID_VOLTAGE);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
    .last_us=399900,.last_seq=7998,.rs_hold_delta=1};
 assert(!MotorIdent_Reference(&s,400000,8000,0,0,.05f,0,&d,&q));
 assert(s.status==MID_DONE && !s.rs_gap_events); /* Original fixed deadline wins. */
 return 0;}
'''
        timing.TimingTests().compile_run(code,'motor-ident-rs-gap')

    def test_actual_binding_supplies_hold_delta_before_decision(self):
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        code=text[start:text.index("'''",start)]
        code=('#define FOC_IDENT_TIMING_TRACE_ENABLE 1\n'
              '#define FOC_IDENT_RS_GAP_ADMISSION_ENABLE 1\n#define __DMB() ((void)0)\n'+code)
        code=code.replace('struct {unsigned source_us;} cl_frame;',
            'struct {unsigned source_us,source_seq;} cl_frame;\n'
            'static unsigned injected_seq_count,cl_last_us,current_hold_total,cl_current_path;')
        code=code.replace('encoder_speed_rpm=3;cl_seq=2;cl_frame.source_us=100;',r'''
 cl_seq=3;cl_frame.source_us=150;cl_frame.source_seq=3;current_hold_total=1;
 assert(MotorIdent_Ref(.05f,0));assert(!stops && motor_ident.rs_skipped_pairs==1);
 assert(motor_ident.last_hold_count==1 && motor_ident.last_seq==3);
 encoder_speed_rpm=3;cl_seq=4;cl_frame.source_us=200;
''')
        code=code.replace('assert(motor_ident.used && !critical);',r'''
 assert(motor_ident.used && !critical);
 MotorIdent_Command("MOTOR TEST IDENT RS GAPS",out,sizeof out);
 assert(strstr(out,"RS_GAPS=1 SKIPPED=1 MAX_GAP=1 BUDGET=16 RUN_LIMIT=2"));
''')
        timing.TimingTests().compile_run(code,'motor-ident-rs-gap-binding')

    def test_host_rs_allows_bounded_gaps_but_l_refuses(self):
        runs=[fixtures.rs_run(a) for a in (.05,.075,.1)]
        for r in runs:
            r['rs_gap_admission']=dict(RS_GAPS=1,SKIPPED=1,MAX_GAP=1,BUDGET=16,RUN_LIMIT=2)
        self.assertAlmostEqual(report.fit_rs(runs)['rs_ohm'],.1)
        r=fixtures.l_run('LD');r['rs_gap_admission']=runs[0]['rs_gap_admission']
        with self.assertRaises(report.Insufficient):report.fit_l(r,.1)
        for mutate in (dict(SKIPPED=17),dict(MAX_GAP=3),dict(BUDGET=999),dict(RS_GAPS=0),dict(MAX_GAP=0)):
            r=fixtures.rs_run(.05)
            r['rs_gap_admission']={**runs[0]['rs_gap_admission'],**mutate}
            with self.assertRaises(report.Insufficient):report.guard(r)

    def test_real_fault_replay_and_frozen_control_old_images(self):
        r=json.loads((ROOT/'tmp/motor-ident-rs50-run-1792499287893157400.json').read_text())
        t=r['ident_timing_failure']['snapshot']
        self.assertEqual((t['prev_seq'],t['seq'],t['delta_us'],t['hold_now']-t['hold_before']),
                         (157402,157404,100,1))
        import re
        a=expanded('a','MotorParameterIdentificationTimingDiagnostic')
        b=expanded('a','MotorParameterIdentificationRsGapDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationTimingDiagnostic/foc2.bin',
             'ecb4b77584e4d589f2881719a1741907335b2e2264d480ee16b815385d9e899c'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
