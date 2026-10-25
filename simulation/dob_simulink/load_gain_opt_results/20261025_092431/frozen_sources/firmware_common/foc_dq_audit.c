#include "foc_dq_audit.h"
_Static_assert(sizeof(FocDqAuditFrame)==64U,"DQA1 frame ABI");

void FocDqAudit_Record(volatile FocDqAudit *a,const FocDqAuditFrame *input)
{
    FocDqAuditFrame f=*input;
    volatile FocDqAuditStats *s=&a->stats;
    uint32_t running=f.flags&DQA_RUNNING;
    if (s->started && !running) return; /* Retain last RUN frame after stop. */
    if (!s->samples) s->first_sat_us=UINT32_MAX;
    ++s->samples;
    if (!isfinite(f.we_rad_s) || !isfinite(f.mech_rpm) ||
        !isfinite(f.vd_dec) || !isfinite(f.vq_dec)) { ++s->invalid_n; return; }
    if (running && !s->started) { s->started=1U;s->start_us=f.us; }
    f.elapsed_us=s->started ? f.us-s->start_us : 0U;
    if (running) ++s->run_n;
    if (fabsf(f.mech_rpm)<=DQ_AUDIT_STATIONARY_RPM) {
        f.flags|=DQA_STATIONARY;++s->zero_n;
        if (fabsf(f.vd_dec)>s->zero_d_max) s->zero_d_max=fabsf(f.vd_dec);
        if (fabsf(f.vq_dec)>s->zero_q_max) s->zero_q_max=fabsf(f.vq_dec);
    }
    if (running && f.elapsed_us<DQ_AUDIT_STARTUP_US) {
        f.flags|=DQA_STARTUP;++s->start_n;
        if (fabsf(f.vd_dec)>s->start_d_max) s->start_d_max=fabsf(f.vd_dec);
        if (fabsf(f.vq_dec)>s->start_q_max) s->start_q_max=fabsf(f.vq_dec);
    }
    if (running && (f.flags&DQA_CRUISE)) {
        ++s->cruise_n;s->cruise_d_sum+=f.vd_dec;s->cruise_q_sum+=f.vq_dec;
    }
    if (running && (f.flags&DQA_SATURATED)) {
        if (!s->sat_n) s->first_sat_us=f.elapsed_us;
        ++s->sat_n;
    }
    if (fabsf(f.we_rad_s)>s->we_abs_max) s->we_abs_max=fabsf(f.we_rad_s);
    /* Independently compare the published mechanical speed with ACTUAL we
     * consumed by this ADC frame. Task publication is not a multiword atomic
     * snapshot; a mismatch is evidence, NOT permission to alter the source. */
    float chain_error=fabsf(f.we_rad_s-f.mech_rpm*(10.0f*6.283185307179586f/60.0f));
    if (chain_error>s->we_chain_error_max) s->we_chain_error_max=chain_error;
    if (f.flags&DQA_ON) {
        float nominal_d=-f.we_rad_s*FOC_DQ_LQ_H*f.iq;
        float nominal_q= f.we_rad_s*FOC_DQ_LD_H*f.id;
        if (nominal_d!=0.0f && ((nominal_d>0)!=(f.vd_dec>0) || f.vd_dec==0)) ++s->nominal_d_bad;
        if (nominal_q!=0.0f && ((nominal_q>0)!=(f.vq_dec>0) || f.vq_dec==0)) ++s->nominal_q_bad;
#if DECOUPLING_SIGN_MODE & 1
        nominal_d=-nominal_d;
#endif
#if DECOUPLING_SIGN_MODE & 2
        nominal_q=-nominal_q;
#endif
        if (fabsf(nominal_d-f.vd_dec)>1e-9f || fabsf(nominal_q-f.vq_dec)>1e-9f) ++s->config_bad;
    } else if (f.vd_dec!=0.0f || f.vq_dec!=0.0f) ++s->config_bad;
    a->latest=f;
}
