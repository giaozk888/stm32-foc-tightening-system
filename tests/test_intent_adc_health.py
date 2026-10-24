"""Real task fault mapping + real window replay; never accesses hardware."""
import subprocess
import sys
import unittest
from pathlib import Path
from test_torque_chain import GCC,function

ROOT=Path(__file__).resolve().parents[1]


class IntentAdcHealthTests(unittest.TestCase):
    def test_real_binding_prioritizes_latched_fault_over_session_loss(self):
        source=(ROOT/'firmware_common/tightening_intent_binding.inc').read_text()
        body=function(source,'IntentPort_Fault')
        harness='''#include <assert.h>
#include <stdint.h>
#include "tightening_intent_fsm.h"
enum {CL_RUNNING=2,CL_DONE=3,CL_FAULT=4};
enum {CL_BAD_ADC=4,CL_BAD_ENCODER=32,CL_COMPUTE_LATE=256,CL_OUTER_STALE=512,CL_OVERSPEED=1024};
enum {FOC_FP_NONE,FOC_FP_CONFIG,FOC_FP_HARDWARE,FOC_FP_HEALTH,FOC_FP_RAW_INVALID,
      FOC_FP_SEQUENCE,FOC_FP_TIMEOUT,FOC_FP_FEEDBACK_INVALID,FOC_FP_FEEDBACK_MISSING,
      FOC_FP_REPAIR_BUDGET,FOC_FP_CONFIRMED_CURRENT,FOC_FP_CURRENT_INVALID};
enum {FOC_FP_HW_TRIP=1};
static TighteningFsm intent_fsm;
static struct {unsigned state;} cl_session;
static struct {struct {unsigned reason,fault_flags;} protection;} cl_safety;
static unsigned adc_fault,foc_fault,cl_fault_valid,cl_flags,tightening_stop_request,foc_fault_reason;
uint8_t TighteningFsm_Busy(const TighteningFsm *s) {
    return s->state>=TF_PRECHECK && s->state<=TF_HOLD;
}
'''
        harness+='static TighteningFsmReason '+body+'''
int main(void) {
    intent_fsm.state=TF_RUNDOWN_START; cl_session.state=CL_FAULT;
    foc_fault=cl_fault_valid=1; cl_flags=CL_BAD_ADC; cl_safety.protection.reason=FOC_FP_HEALTH;
    assert(IntentPort_Fault()==TF_REASON_ADC_HEALTH); /* Recorded A728 case. */
    cl_flags=CL_OVERSPEED; assert(IntentPort_Fault()==TF_REASON_OVERSPEED);
    cl_flags=CL_BAD_ENCODER; assert(IntentPort_Fault()==TF_REASON_ENCODER_FAULT);
    cl_flags=CL_BAD_ADC; cl_safety.protection.reason=FOC_FP_CURRENT_INVALID;
    assert(IntentPort_Fault()==TF_REASON_CURRENT_INVALID);
    cl_safety.protection.reason=FOC_FP_CONFIRMED_CURRENT;
    assert(IntentPort_Fault()==TF_REASON_OVERCURRENT);
    cl_safety.protection.reason=FOC_FP_HARDWARE; cl_safety.protection.fault_flags=FOC_FP_HW_TRIP;
    assert(IntentPort_Fault()==TF_REASON_OVERCURRENT);
    cl_safety.protection.fault_flags=0; cl_safety.protection.reason=FOC_FP_TIMEOUT;
    assert(IntentPort_Fault()==TF_REASON_TIMEOUT); /* Genuine timeout is retained. */
    cl_flags=CL_COMPUTE_LATE; cl_safety.protection.reason=FOC_FP_HEALTH;
    assert(IntentPort_Fault()==TF_REASON_TIMEOUT);
    cl_flags=CL_OUTER_STALE; assert(IntentPort_Fault()==TF_REASON_TIMEOUT);
    cl_flags=0; assert(IntentPort_Fault()==TF_REASON_FAULT); /* Driver/unknown not invented timeout. */
    cl_fault_valid=foc_fault=0;
    assert(IntentPort_Fault()==TF_REASON_TIMEOUT); /* Unexplained lost session remains failure. */
    tightening_stop_request=1; assert(IntentPort_Fault()==TF_REASON_NONE);
    tightening_stop_request=0; intent_fsm.state=TF_PRECHECK; assert(IntentPort_Fault()==TF_REASON_NONE);
    intent_fsm.state=TF_IDLE; assert(IntentPort_Fault()==TF_REASON_NONE);
    intent_fsm.state=TF_RUNDOWN; cl_session.state=CL_RUNNING; assert(IntentPort_Fault()==TF_REASON_NONE);
    adc_fault=1; assert(IntentPort_Fault()==TF_REASON_ADC_HEALTH);
    tightening_stop_request=1; assert(IntentPort_Fault()==TF_REASON_ADC_HEALTH); /* STOP cannot erase fault. */
    return 0;
}
'''
        out=ROOT/'tests/intent_fsm_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('fault-map'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
                input=harness,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_retained_window_failure_replays_without_relaxation(self):
        out=ROOT/'tests/intent_fsm_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('adc-window'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/intent_adc_health_regression.c'),
                str(ROOT/'firmware_common/foc_adc_window.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('deficit=2 ticks',p.stdout)

    def test_pinned_offline_capture_reports_plan_failure_not_pair_loss(self):
        sys.path.insert(0,str(ROOT/'tools'))
        from intent_adc_health_report import report
        result=report()
        self.assertTrue(result['capture_identity_verified'])
        self.assertFalse(result['hardware_access'])
        self.assertEqual(result['adc_pair_misses'],0)
        self.assertEqual(result['plan_failures'],1)
        self.assertEqual(result['last_plan_status_name'],'TOO_SHORT')
        self.assertEqual(result['replayed_phase_ccr_uvw'],[1891,2401,1848])
        self.assertEqual(result['required_earliest_tick'],4186)
        self.assertEqual(result['latest_tick'],4184)
        self.assertEqual(result['deficit_ticks'],2)


if __name__=='__main__': unittest.main()
