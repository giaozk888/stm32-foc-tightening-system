"""Rs bad-current admission count-only; fixed lease/quality/hard safety frozen."""
import copy
import hashlib
import json
import re
import sys
import unittest
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded
import test_motor_ident_timing as timing
import test_motor_identification as fixtures
sys.path.insert(0,str(ROOT/'tools'))
import motor_identification_report as report

DEFINES='''
#define FOC_IDENT_CURRENT_REJECT_ENABLE 1
#define FOC_IDENT_TIMING_TRACE_ENABLE 1
#define FOC_IDENT_RS_GAP_ADMISSION_ENABLE 1
#define FOC_IDENT_RS_GAP_COUNT_ONLY 1
#define FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT 1
#define FOC_IDENT_RS_REJECT_COUNT_ONLY 1
#define MID_RS_SOFT_DT_MAX_US 100U
#define MID_TRAVEL_EXIT_ENABLE 0
'''


class RsRejectCountTests(unittest.TestCase):
    def test_replay_three_rejects_long_run_saturation_and_recovery(self):
        saved=json.loads((ROOT/'tmp/motor-ident-rs50-run-1792555719749485400.json').read_text())
        self.assertEqual((saved['ident_ram']['last_seq'],saved['ident_ram']['last_us'],
                          saved['current_admission_ram']['run']), (160973,8166912,3))
        timing.TimingTests().compile_run(DEFINES+r'''
#include <assert.h>
#include "motor_identification.h"
int main(void){float d=0,q=0;
 assert(sizeof(MotorIdentification)==1740);
 /* Frozen end context, replay three out-of-admission pairs. Exact final
  * amplitudes were not captured: these are explicit synthetic >.20A values. */
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
  .start_us=8018330,.last_us=8166762,.last_seq=160970,
  .current_good_count=2899,.current_reject_count=60,.max_current_reject_run=2};
 for(unsigned k=1;k<=3;++k){
  assert(MotorIdent_Reference(&s,8166762+50*k,160970+k,0,0,.25f,0,&d,&q));
  assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=8166762+50*k,.id=.25f,.vd=.01f}));
 }
 assert(s.status==MID_ACTIVE && s.reason==MID_OK && s.current_reject_run==3);
 assert(s.current_reject_count==63 && !s.count && d==.05f && q==0);
 /* More than uint8_t capacity never wraps the run back to zero. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 for(unsigned k=1;k<=300;++k){
  assert(MotorIdent_Reference(&s,50*k,k,0,0,0,-.21f,&d,&q));
  assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=50*k,.iq=-.21f,.vd=.01f}));
 }
 assert(s.current_reject_count==300 && s.current_reject_run==255 &&
        s.max_current_reject_run==255 && !s.count);
 assert(MotorIdent_Reference(&s,15050,301,0,0,.05f,0,&d,&q));
 assert(!s.current_reject_run && s.max_current_reject_run==255 && s.current_good_count==1);
 /* Both L axes keep their original third rejection exit. */
 for(unsigned m=MID_LD;m<=MID_LQ;++m){
  s=(MotorIdentification){.mode=m,.status=MID_ACTIVE,.current_a=.1f};
  for(unsigned k=1;k<=3;++k){
   unsigned ok=MotorIdent_Reference(&s,k*50,k,0,0,.21f,0,&d,&q);assert(ok==(k<3));
  }
  assert(s.status==MID_ABORT && s.reason==MID_CURRENT && d==0 && q==0);
 }
 return 0;}
''','rs-reject-count-replay')

    def test_fixed_duration_no_bad_rows_and_independent_exits(self):
        timing.TimingTests().compile_run(DEFINES+r'''
#include <assert.h>
#include "motor_identification.h"
int main(void){float d=0,q=0;
 for(unsigned all_bad=0;all_bad<=1;++all_bad){
  MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
  for(unsigned seq=1;seq<=8000;++seq){
   unsigned now=seq*50;
   float id=(all_bad || now<15000 || (seq%200<5))? .21f:.05f;
   unsigned ok=MotorIdent_Reference(&s,now,seq,0,0,id,0,&d,&q);
   if(now==400000){assert(!ok);break;}
   assert(ok);
   assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=now,.seq=seq,.id=id,
       .id_ref=d,.iq_ref=q,.vd=.005f}));
  }
  assert(s.status==MID_DONE && d==0 && q==0);
  if(all_bad){assert(!s.count && s.current_reject_run==255);}
  else{assert(s.count==32);for(unsigned k=0;k<32;++k)assert(s.rows[k].id==.05f);}
 }
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 assert(!MotorIdent_Reference(&s,50,1,0,3,.05f,0,&d,&q));assert(s.reason==MID_MOTION);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE};
 assert(!MotorIdent_Reference(&s,50,1,0,0,NAN,0,&d,&q));assert(s.reason==MID_BAD_DATA);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE};
 assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f}));assert(s.reason==MID_VOLTAGE);
 return 0;}
''','rs-reject-count-lease')

    def test_actual_command_explicit_rs_and_l_policy(self):
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        code=DEFINES+'\n#define __DMB() ((void)0)\n'+text[start:text.index("'''",start)]
        code=code.replace('struct {unsigned source_us;} cl_frame;',
            'struct {unsigned source_us,source_seq; unsigned short u,v;} cl_frame;\n'
            'static unsigned injected_seq_count,cl_last_us,current_hold_total,cl_current_path;')
        code=code.replace('assert(motor_ident.used && !critical);',r'''
 assert(motor_ident.used && !critical);
 motor_ident.current_reject_count=3;motor_ident.current_reject_run=motor_ident.max_current_reject_run=3;
 MotorIdent_Command("MOTOR TEST IDENT REJECT",out,sizeof out);
 assert(strstr(out,"RUN=3 MAX_RUN=3 REJECT_MAX=0 RUN_LIMIT=0"));
 assert(strstr(out,"TOTAL_STOP=0 RUN_STOP=0 RUN_SAT=255"));
 motor_ident.mode=MID_LD;
 MotorIdent_Command("MOTOR TEST IDENT REJECT",out,sizeof out);
 assert(strstr(out,"REJECT_MAX=16 RUN_LIMIT=3"));
 assert(strstr(out,"TOTAL_STOP=1 RUN_STOP=1 RUN_SAT=255"));
''')
        timing.TimingTests().compile_run(code,'rs-reject-count-binding')

    def test_host_requires_explicit_policy_complete_clean_data_not_done_only(self):
        runs=[fixtures.rs_run(a) for a in (.05,.075,.1)]
        for r in runs:
            r['current_admission']=dict(REJECT=600,GOOD=7000,MAX_RUN=255,REJECT_MAX=0,
                                        RUN_LIMIT=0,TOTAL_STOP=0,RUN_STOP=0,RUN_SAT=255)
        self.assertAlmostEqual(report.fit_rs(runs)['rs_ohm'],.1)
        for changes in (dict(RUN_STOP=1),dict(RUN_LIMIT=3),dict(RUN_SAT=256),
                        dict(MAX_RUN=256),dict(GOOD=31),dict(REJECT=9000)):
            r=copy.deepcopy(runs[0]);r['current_admission'].update(changes)
            with self.assertRaises(report.Insufficient):report.guard(r)
        for case in ('empty','bad_row','fault','L','dense','outside_window'):
            r=copy.deepcopy(runs[0])
            if case=='empty':r['rows']=[]
            elif case=='bad_row':r['rows'][0]['id']=.21
            elif case=='fault':r['protection_evidence']['fault']=1
            elif case=='L':r['mode']='LD'
            elif case=='dense':r['rows'][1]['us']=200050
            elif case=='outside_window':r['rows'][-1]['us']=400000
            with self.assertRaises(report.Insufficient):report.guard(r)
        # Old explicit policy still rejects a three-sample run.
        r=fixtures.rs_run(.05)
        r['current_admission']=dict(REJECT=3,GOOD=7000,MAX_RUN=3,REJECT_MAX=0,RUN_LIMIT=3,TOTAL_STOP=0)
        with self.assertRaises(report.Insufficient):report.guard(r)

    def test_frozen_control_old_images_and_default_off(self):
        a=expanded('a','MotorParameterIdentificationRsGapCountDiagnostic')
        b=expanded('a','MotorParameterIdentificationRsRejectCountDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_Pair')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationRsGapCountDiagnostic/foc2.bin',
             '68f066ad4fad8df0737271f0b0eec3937266f05ebea253de83f78eea8b212c06'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)
        config=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertIn('option(FOC_IDENT_RS_REJECT_COUNT_ONLY ',config)


if __name__=='__main__':unittest.main()
