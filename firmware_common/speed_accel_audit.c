#include "speed_accel_audit.h"
#include <math.h>
#include <string.h>
_Static_assert(sizeof(SpeedAccelAuditFrame)==64U,"Binary audit frame ABI");
_Static_assert(sizeof(SpeedAccelAuditMeta)==88U,"Binary audit header ABI");
int SpeedAccelAudit_GainPercent(const char *arg)
{
    if (!strcmp(arg,"0")) return 0;
    if (!strcmp(arg,"25")) return 25;
    if (!strcmp(arg,"50")) return 50;
    if (!strcmp(arg,"100")) return 100;
    return -1;
}
void SpeedAccelAudit_Reset(SpeedAccelAudit *s)
{
    /* Old frames are invalidated by count/generation; do not clear 1 KB
     * inside an existing reset owner or allocate a 1 KB stack temporary. */
    uint32_t generation=s->meta.generation+1U;
    s->meta=(SpeedAccelAuditMeta){.generation=generation};
}
void SpeedAccelAudit_Push(SpeedAccelAudit *s,const SpeedAccelFfFrame *f,float friction,
    uint32_t phase,float dt,float ka,float limit,uint8_t aw_limited,uint8_t release,
    float previous_integrator,float candidate_integrator)
{
    SpeedAccelAuditMeta *m=&s->meta;
    if (!f->valid) return;
    if (!m->samples) { m->start_ms=f->ms;m->first_sat_ms=UINT32_MAX; }
    ++m->samples;
    m->effective_ka=ka;
    if (m->trajectory_updates!=m->samples) ++m->sync_errors;
    if (f->enabled) ++m->enabled_samples;
    float expected=f->enabled ? ka*f->accel_ref_rpm_s : 0.0f;
    if (f->enabled && ka>0.0f && f->accel_ref_rpm_s*f->iq_ff_a<0.0f) ++m->sign_errors;
    if (f->accel_ref_rpm_s==0.0f && f->iq_ff_a!=0.0f) ++m->zero_ff_errors;
    if (!isfinite(f->iq_ff_a) || fabsf(f->iq_ff_a-expected)>0.000001f) ++m->formula_errors;
    if (f->iq_pi_a*f->iq_ff_a<0.0f) ++m->pi_ff_opposed; /* Evidence, not automatic fault. */
    if (aw_limited) ++m->aw_limited_samples;
    /* Test the TENTATIVE total (PI candidate + both FFs), not the final
     * saturation flag which already includes AW admission at the boundary. */
    float tentative=((f->iq_pi_a-f->speed_integrator_a)+candidate_integrator)+expected+friction;
    if (aw_limited && !release && fabsf(tentative)<limit-0.000001f) ++m->unexpected_aw_samples;
    if (!release && ((candidate_integrator>=previous_integrator &&
        (f->speed_integrator_a<previous_integrator-0.000001f || f->speed_integrator_a>candidate_integrator+0.000001f)) ||
        (candidate_integrator<previous_integrator &&
        (f->speed_integrator_a>previous_integrator+0.000001f || f->speed_integrator_a<candidate_integrator-0.000001f))))
        ++m->unexpected_aw_samples;
    if (f->saturated) {
        ++m->sat_samples;m->saturation_s+=dt;
        if (m->first_sat_ms==UINT32_MAX) m->first_sat_ms=f->ms-m->start_ms;
    }
    m->max_abs_accel=fmaxf(m->max_abs_accel,fabsf(f->accel_ref_rpm_s));
    m->max_abs_ff=fmaxf(m->max_abs_ff,fabsf(f->iq_ff_a));
    if (limit>0.0f) m->max_ff_limit_ratio=fmaxf(m->max_ff_limit_ratio,fabsf(f->iq_ff_a)/limit);
    m->max_abs_integrator=fmaxf(m->max_abs_integrator,fabsf(f->speed_integrator_a));
    if (m->trace_count>=SPEED_ACCEL_AUDIT_CAPACITY ||
        (m->trace_count && (uint32_t)(f->ms-m->last_trace_ms)<SPEED_ACCEL_AUDIT_SPACING_MS)) return;
    SpeedAccelAuditFrame frame={.seq=f->seq,.ms=f->ms,.trajectory_update=m->trajectory_updates,
        .speed_ref=f->speed_ref_rpm,.speed_meas=f->speed_meas_rpm,
        .speed_error=f->speed_ref_rpm-f->speed_meas_rpm,.accel_ref=f->accel_ref_rpm_s,
        .iq_pi=f->iq_pi_a,.iq_acc_ff=f->iq_ff_a,.iq_fric=friction,
        .iq_raw=f->iq_raw_a,.iq_cmd=f->iq_ref_a,.integrator=f->speed_integrator_a,
        .trajectory_phase=phase,.flags=(f->enabled?SAA_ON:0U)|(f->saturated?SAA_SAT:0U)|
            (aw_limited?SAA_AW_LIMITED:0U)|(release?SAA_RELEASE:0U),.dt_s=dt};
    s->frames[m->trace_count]=frame;
    m->last_trace_ms=f->ms;
    ++m->trace_count; /* Single task writer; MonitorTask copies under task critical section. */
}
