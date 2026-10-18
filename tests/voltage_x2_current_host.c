/* Includes the unmodified current-loop body extracted from APP A/B. No devices. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "voltage_x2_constants.inc"
#define FOC_PROTECTED_CLOSED_LOOP 1
#define FOC_CURRENT_TREND4 1
#define FOC_FAST_CURRENT_REJECT 1
#define FOC_FAST_MATH 1
#define FOC_CURRENT_FAULT_TRACE_ENABLE 0
#define FocProfile_Mark(x) ((void)0)
static int foc_enable=1,encoder_valid=1;
static struct { float iu_A,iv_A,iw_A,measurement_angle; } cl_frame;
static float encoder_theta_e_pred;
static float foc_id_ref_A,foc_iq_ref_A,foc_int_d_V,foc_int_q_V;
static float foc_id_A,foc_iq_A,foc_vd_V,foc_vq_V;
static float foc_duty_u,foc_duty_v,foc_duty_w;
static uint32_t foc_control_count;
static float sink_u,sink_v,sink_w;
static void PWM_SetDuty(float u,float v,float w) { sink_u=u; sink_v=v; sink_w=w; }
static float ClampFloat(float x,float lo,float hi) { return x<lo?lo:x>hi?hi:x; }
static int FocFast_SinCos(float t,float *s,float *c) { *s=sinf(t); *c=cosf(t); return 1; }
static void ProtectedLoop_EmergencyOff(uint32_t f) { (void)f; assert(0); }
static void ProtectedLoop_AdvanceAngle(void) { }
#define CL_BAD_ENCODER 1U
#include "voltage_x2_current_body.inc"
int main(int argc,char **argv)
{
    assert(argc==2); int test=atoi(argv[1]);
    assert(FOC_INTEGRATOR_LIMIT_V==.75f);
    if (test==0) {
        foc_iq_ref_A=.1f; FOC_CurrentLoopStep(0,0,0,0);
        assert(fabsf(foc_vq_V-.00894f)<1e-6f);
        assert(foc_control_count==1 && sink_v>.5f && sink_w<.5f);
    } else if (test==1) {
        foc_iq_ref_A=.15f; cl_frame.iu_A=.04f;
        cl_frame.iv_A=(.05f*1.73205080757f-.04f)*.5f;
        for (unsigned i=0;i<20000;++i) FOC_CurrentLoopStep(0,0,0,0);
        assert(fabsf(foc_iq_A-.05f)<1e-6f);
        assert(fabsf(foc_int_d_V)<=.75f && fabsf(foc_int_q_V)<=.75f);
        float magnitude=hypotf(foc_vd_V,foc_vq_V);
        assert(magnitude<=FOC_VOLTAGE_LIMIT_V+1e-5f);
        if (FOC_VOLTAGE_LIMIT_V>1) assert(magnitude>1.06f && magnitude<1.08f);
        else assert(magnitude>.799f && magnitude<.801f);
        printf("fixed-input vector=%.6f V, NOT a motor plant simulation\n",(double)magnitude);
    } else if (test==2) {
        foc_iq_ref_A=100; foc_id_ref_A=100;
        for (unsigned i=0;i<1000;++i) FOC_CurrentLoopStep(0,0,0,0);
        assert(fabsf(hypotf(foc_vd_V,foc_vq_V)-FOC_VOLTAGE_LIMIT_V)<1e-5f);
        assert(fabsf(foc_int_d_V)<=.75f && fabsf(foc_int_q_V)<=.75f);
        assert(sink_u>0 && sink_u<1 && sink_v>0 && sink_v<1 && sink_w>0 && sink_w<1);
    } else if (test==3 || test==4) {
        if (test==3) foc_enable=0; else encoder_valid=0;
        foc_iq_ref_A=.15f; FOC_CurrentLoopStep(0,0,0,0);
        assert(!foc_control_count && sink_u==.5f && sink_v==.5f && sink_w==.5f);
    } else return 2;
    return 0;
}
