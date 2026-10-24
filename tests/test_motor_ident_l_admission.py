"""L-axis opt-in admission only; finite lease and original control frozen."""
import copy
import re
import sys
import unittest
from test_motor_ident_timing import TimingTests
from test_motor_ident_rs_reject_count import DEFINES
from test_motor_identification import l_run
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import motor_identification_report as report


class LAdmissionTests(unittest.TestCase):
    def test_actual_c_dt57_rejects_and_explained_gaps_both_axes(self):
        TimingTests().compile_run(DEFINES+'\n#define FOC_IDENT_L_RS_ADMISSION_ENABLE 1\n'+r'''
#include <assert.h>
#include "motor_identification.h"
int main(void){float d=0,q=0;
 assert(sizeof(MotorIdentification)==1740);
 for(unsigned mode=MID_LD;mode<=MID_LQ;++mode){
  MotorIdentification s={.mode=mode,.status=MID_ACTIVE,.current_a=.1f,
     .start_us=7986290,.last_us=7986295,.last_seq=157360};
  assert(MotorIdent_Reference(&s,7986352,157361,0,0,0,0,&d,&q));
  assert(!s.timing_failure.valid); /* Actual prior 57us failure. */
  s=(MotorIdentification){.mode=mode,.status=MID_ACTIVE,.current_a=.1f};
  for(unsigned k=1;k<=300;++k){
   assert(MotorIdent_Reference(&s,k*50,k,0,0,.21f,0,&d,&q));
   assert(MotorIdent_Record(&s,(MotorIdentFrame){.us=k*50,.id=.21f,.vd=.01f}));
  }
  assert(!s.count && s.current_reject_count==300 && s.max_current_reject_run==255);
  s.rs_hold_delta=1;
  assert(MotorIdent_Reference(&s,15100,302,0,0,.05f,0,&d,&q));
  assert(s.rs_skipped_pairs==1 && s.current_reject_run==0);
  s.rs_hold_delta=0;
  assert(!MotorIdent_Reference(&s,15300,306,0,0,.05f,0,&d,&q));
  assert(s.reason==MID_TIMING); /* No unexplained/long-gap bypass. */
  s=(MotorIdentification){.mode=mode,.status=MID_ACTIVE};
  assert(!MotorIdent_Reference(&s,104000,2080,0,0,.05f,0,&d,&q));
  assert(s.status==MID_DONE && d==0 && q==0);
  s=(MotorIdentification){.mode=mode,.status=MID_ACTIVE};
  assert(!MotorIdent_Reference(&s,50,1,0,3,.05f,0,&d,&q));assert(s.reason==MID_MOTION);
  s=(MotorIdentification){.mode=mode,.status=MID_ACTIVE};
  assert(!MotorIdent_Reference(&s,50,1,0,0,NAN,0,&d,&q));assert(s.reason==MID_BAD_DATA);
  s=(MotorIdentification){.mode=mode,.status=MID_ACTIVE};
  assert(!MotorIdent_Record(&s,(MotorIdentFrame){.vd=.201f}));assert(s.reason==MID_VOLTAGE);
 }
 return 0;}
''','l-admission-replay')

    def test_explicit_new_policy_no_silent_upgrade_or_interpolation(self):
        for mode in ('LD','LQ'):
            r=l_run(mode)
            r.update(admission_policy='L_RS_ADMISSION_V1',
                time_policy=dict(L_RS_ADMISSION='1',L_DT_MAX='100'),
                current_admission=dict(REJECT=100,GOOD=1900,MAX_RUN=100,REJECT_MAX=0,
                    RUN_LIMIT=0,TOTAL_STOP=0,RUN_STOP=0,RUN_SAT=255),
                rs_gap_admission=dict(RS_GAPS=20,SKIPPED=20,MAX_GAP=1,BUDGET=0,RUN_LIMIT=2,TOTAL_STOP=0))
            self.assertEqual(len(report.guard(r)),32)
            self.assertGreater(report.fit_l(r,.1)['inductance_h'],0)
            for key in ('admission_policy','time_policy'):
                bad=copy.deepcopy(r);bad.pop(key)
                with self.assertRaises(report.Insufficient):report.guard(bad)
            for mutate in (lambda b:b['rows'][10].update(seq=123),
                           lambda b:b['rows'][10].update(us=b['rows'][9]['us']+70),
                           lambda b:b['latch_evidence'].update(verified=False)):
                bad=copy.deepcopy(r);mutate(bad)
                with self.assertRaises(report.Insufficient):report.fit_l(bad,.78)

    def test_control_and_pwm_functions_frozen(self):
        a=expanded('a','MotorParameterIdentificationRsRejectCountDiagnostic')
        b=expanded('a','MotorParameterIdentificationLAdmissionDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                               'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_Pair')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)


if __name__=='__main__':unittest.main()
