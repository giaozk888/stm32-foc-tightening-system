"""Rs explained gaps count-only; old policy/L paths and control remain frozen."""
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
#define MID_RS_SOFT_DT_MAX_US 100U
#define MID_TRAVEL_EXIT_ENABLE 0
'''


class RsGapCountTests(unittest.TestCase):
    def test_real_failure_replay_and_unchanged_local_limits(self):
        saved=json.loads((ROOT/'tmp/motor-ident-rs50-run-1792554750041524400.json').read_text())
        t=saved['ident_timing_failure']['snapshot'];g=saved['rs_gap_ram']
        self.assertEqual((t['delta_seq'],t['delta_us'],t['hold_now']-t['hold_before'],g['skipped']),
                         (2,100,1,16))
        code=DEFINES+r'''
#include <assert.h>
#include <stddef.h>
#include "motor_identification.h"
int main(void){float d=0,q=0;
 assert(sizeof(MotorIdentification)==1740);
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
  .start_us=8001286,.last_seq=161597,.last_us=8198103,.rs_hold_delta=1,
  .rs_gap_events=16,.rs_skipped_pairs=16,.rs_max_skipped=1};
 assert(MotorIdent_Reference(&s,8198203,161599,0,0,.05f,0,&d,&q));
 assert(s.status==MID_ACTIVE && s.reason==MID_OK && !s.timing_failure.valid);
 assert(s.rs_gap_events==17 && s.rs_skipped_pairs==17 && d==.05f && q==0);
 for(unsigned mode=MID_RS;mode<=MID_LQ;++mode)
 for(unsigned ds=1;ds<=4;++ds)for(unsigned hold=0;hold<=3;++hold)
 for(unsigned dt=40;dt<=225;dt+=5){
  s=(MotorIdentification){.mode=mode,.status=MID_ACTIVE,.current_a=.05f,
     .last_us=100,.last_seq=10,.rs_hold_delta=hold,.rs_skipped_pairs=40};
  unsigned allowed=(ds==1 && dt>=45 && dt<=(mode==MID_RS?100:55)) ||
    (mode==MID_RS && ds>=2 && ds<=3 && hold==ds-1 && dt>=45*ds && dt<=55*ds);
  unsigned ok=MotorIdent_Reference(&s,100+dt,10+ds,0,0,.05f,0,&d,&q);
  assert(ok==allowed);
  if(!allowed) assert(s.reason==MID_TIMING && d==0 && q==0);
 }
 /* Sequence/time wrap still uses unsigned deltas. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f,
  .start_us=0xffffff00U,.last_us=0xfffffff0U,.last_seq=0xffffffffU,.rs_hold_delta=1};
 assert(MotorIdent_Reference(&s,84,1,0,0,.05f,0,&d,&q));
 assert(s.rs_skipped_pairs==1);
 return 0;}
'''
        timing.TimingTests().compile_run(code,'rs-gap-count-replay')

    def test_fixed_lease_full_rows_and_bad_samples_never_in_estimator(self):
        timing.TimingTests().compile_run(DEFINES+r'''
#include <assert.h>
#include "motor_identification.h"
int main(void){float d=0,q=0;
 MotorIdentification s={.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 for(unsigned seq=1;seq<=8000;++seq){
  if(seq%47==0){++s.rs_hold_delta;continue;} /* Actual held frame: no fake row. */
  unsigned now=seq*50;
  float id=(seq%113==0)? .21f:.05f;
  unsigned ok=MotorIdent_Reference(&s,now,seq,0,0,id,0,&d,&q);
  if(now==400000){assert(!ok && s.status==MID_DONE);break;}
  assert(ok);s.rs_hold_delta=0;
  assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=now,.seq=seq,.id=id,
      .id_ref=d,.iq_ref=q,.vd=.005f}));
 }
 assert(s.rs_skipped_pairs>16 && s.current_reject_count>16);
 assert(s.count==32 && s.status==MID_DONE && s.reason==MID_OK && d==0 && q==0);
 for(unsigned k=0;k<s.count;++k){
  assert(s.rows[k].seq%47 && s.rows[k].seq%113 && s.rows[k].id==.05f);
  assert(s.rows[k].us>=200000 && s.rows[k].us<400000);
 }
 /* Persistent bad current still stops on the original third rejected pair. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE,.current_a=.05f};
 for(unsigned k=1;k<=3;++k){
  unsigned ok=MotorIdent_Reference(&s,k*50,k,0,0,.21f,0,&d,&q);
  assert(ok==(k<3));
 }
 assert(s.reason==MID_CURRENT && s.max_current_reject_run==3 && !s.count);
 /* Nonfinite/motion/voltage exit conditions remain independent. */
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE};
 assert(!MotorIdent_Reference(&s,50,1,0,3,.05f,0,&d,&q));assert(s.reason==MID_MOTION);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE};
 assert(!MotorIdent_Reference(&s,50,1,0,0,NAN,0,&d,&q));assert(s.reason==MID_BAD_DATA);
 s=(MotorIdentification){.mode=MID_RS,.status=MID_ACTIVE};
 assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f}));assert(s.reason==MID_VOLTAGE);
 return 0;}
''','rs-gap-count-lease')

    def test_actual_binding_reports_explicit_count_only_policy(self):
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        code=text[start:text.index("'''",start)]
        code=DEFINES+'\n#define __DMB() ((void)0)\n'+code
        code=code.replace('struct {unsigned source_us;} cl_frame;',
            'struct {unsigned source_us,source_seq; unsigned short u,v;} cl_frame;\n'
            'static unsigned injected_seq_count,cl_last_us,current_hold_total,cl_current_path;')
        code=code.replace('assert(motor_ident.used && !critical);',r'''
 assert(motor_ident.used && !critical);
 MotorIdent_Command("MOTOR TEST IDENT RS GAPS",out,sizeof out);
 assert(strstr(out,"BUDGET=0 RUN_LIMIT=2 TOTAL_STOP=0"));
 motor_ident.mode=MID_LD;
 MotorIdent_Command("MOTOR TEST IDENT RS GAPS",out,sizeof out);
 assert(strstr(out,"BUDGET=16 RUN_LIMIT=2 TOTAL_STOP=1"));
''')
        timing.TimingTests().compile_run(code,'rs-gap-count-binding')

    def test_host_new_policy_preserves_old_and_quality_requirements(self):
        runs=[fixtures.rs_run(a) for a in (.05,.075,.1)]
        for r in runs:r['rs_gap_admission']=dict(RS_GAPS=35,SKIPPED=40,MAX_GAP=2,
                                               BUDGET=0,RUN_LIMIT=2,TOTAL_STOP=0)
        self.assertAlmostEqual(report.fit_rs(runs)['rs_ohm'],.1)
        for mutate in (dict(BUDGET=16),dict(TOTAL_STOP=1),dict(MAX_GAP=3),
                       dict(SKIPPED=8001),dict(RS_GAPS=0),dict(SKIPPED=100)):
            r=copy.deepcopy(runs[0]);r['rs_gap_admission'].update(mutate)
            with self.assertRaises(report.Insufficient):report.guard(r)
        for case in ('few_rows','late_row','too_dense','nonfinite','bad_noise','fault','missing_proof','L_mode'):
            r=copy.deepcopy(runs[0])
            if case=='few_rows':r['rows'].pop()
            elif case=='late_row':r['rows'][-1]['us']=400000
            elif case=='too_dense':r['rows'][1]['us']=200050
            elif case=='nonfinite':r['rows'][0]['id']=float('nan')
            elif case=='bad_noise':
                for k,row in enumerate(r['rows']):row['id']+= .04 if k%2 else -.04
            elif case=='fault':r['fault']=1
            elif case=='missing_proof':r.pop('protection_evidence')
            elif case=='L_mode':r['mode']='LD'
            with self.assertRaises(report.Insufficient):report.fit_rs([r,*runs[1:]])
        # Old explicit bounded captures still fail above 16; no silent upgrade.
        r=copy.deepcopy(runs[0]);r['rs_gap_admission'].update(BUDGET=16,TOTAL_STOP=1)
        with self.assertRaises(report.Insufficient):report.guard(r)

    def test_candidate_frozen_control_and_old_binaries(self):
        a=expanded('a','MotorParameterIdentificationEncoderTimingDiagnostic')
        b=expanded('a','MotorParameterIdentificationRsGapCountDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_Pair')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationEncoderTimingDiagnostic/foc2.bin',
             '09ac2082aec995fd6be5e826a887aba2513521319cf13783119157c460fda661'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
