/* The included body/macros are mechanically extracted, unmodified, from each
 * APP main.c by the test. PWM sink is a mock, not physical actuation. */
#include <assert.h>
#include <stdint.h>
#include <math.h>
#include <stdlib.h>
#include "foc_feedback_binding_stm32.h"
#include "control_chain_current_constants.inc"
static int active=1, encoder_valid=1;
static int IsolatedBench_Active(void) { return active; }
static FocFeedbackFrame foc_feedback_control_frame;
static float foc_id_ref_A, foc_iq_ref_A, foc_int_d_V, foc_int_q_V;
static float encoder_theta_e_pred, encoder_omega_e_rad_s;
static float foc_id_A, foc_iq_A, foc_vd_V, foc_vq_V;
static float foc_duty_u, foc_duty_v, foc_duty_w;
static uint32_t foc_control_count;
static float sink_u, sink_v, sink_w;
static void PWM_SetDuty(float u,float v,float w) { sink_u=u; sink_v=v; sink_w=w; }
static float ClampFloat(float value,float low,float high)
{ return value<low?low:value>high?high:value; }
#include "control_chain_current_body.inc"
int main(int argc,char **argv)
{
    assert(argc==2); int n=atoi(argv[1]);
    foc_feedback_control_frame=(FocFeedbackFrame){.ready=1U};
    if (n==0) {
        foc_iq_ref_A=0.10f;
        FOC_CurrentLoopStep(0U,4095U,4095U,0U);
        assert(foc_control_count==1U && foc_vq_V>0.008f && foc_vq_V<0.010f);
        assert(foc_id_A==0.0f && foc_iq_A==0.0f);
        assert(sink_u==0.5f && sink_v>0.5f && sink_w<0.5f);
    } else if (n==1) {
        /* Delayed Park angle paired with measurement; actuation angle current. */
        foc_feedback_control_frame.iu_A=0.20f;
        foc_feedback_control_frame.iv_A=-0.10f;
        foc_feedback_control_frame.iw_A=-0.10f;
        foc_feedback_control_frame.measurement_angle=0.0f;
        foc_feedback_control_frame.actuation_angle=TWO_PI_F/4.0f;
        FOC_CurrentLoopStep(4095U,0U,0U,4095U);
        assert(fabsf(foc_id_A-0.20f)<0.0001f && fabsf(foc_iq_A)<0.0001f);
        assert(foc_vd_V<0.0f && fabsf(foc_vq_V)<0.0001f);
        assert(sink_u>0.49999f && sink_u<0.50001f && sink_v<0.5f && sink_w>0.5f);
    } else if (n==2) {
        foc_iq_ref_A=100.0f;
        for (unsigned i=0;i<1000U;++i) FOC_CurrentLoopStep(0U,0U,0U,0U);
        assert(foc_vd_V*foc_vd_V+foc_vq_V*foc_vq_V<=0.6401f);
        assert(fabsf(foc_int_q_V)<=FOC_INTEGRATOR_LIMIT_V);
        assert(sink_u>0.0f && sink_v<1.0f && sink_w>0.0f);
        assert(foc_control_count==1000U);
    } else if (n==3) {
        active=0; foc_iq_ref_A=0.10f;
        FOC_CurrentLoopStep(1600U,1600U,1600U,1600U);
        assert(!foc_control_count && sink_u==0.5f && sink_v==0.5f && sink_w==0.5f);
        active=1; encoder_valid=0;
        FOC_CurrentLoopStep(1600U,1600U,1600U,1600U);
        assert(!foc_control_count);
    } else return 2;
    assert(foc_duty_u==sink_u || !foc_control_count);
    return 0;
}
