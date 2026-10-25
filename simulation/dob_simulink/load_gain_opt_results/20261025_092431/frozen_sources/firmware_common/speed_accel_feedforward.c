#include "speed_accel_feedforward.h"
#include <math.h>

static float clamp(float x,float limit)
{ return x < -limit ? -limit : x > limit ? limit : x; }

SpeedAccelFfResult SpeedAccelFf_Apply(float previous,float candidate,float p,
    float accel_ref,float ka,float iq_limit,float integral_limit,uint8_t release,uint8_t enabled)
{
    float ff=enabled ? ka*accel_ref : 0.0f;
    float admitted;
    uint8_t limited;
    if (ff==0.0f) {
        /* Exact existing admission/rounding when OFF, Ka=0, or cruise. */
        SpeedPiAntiWindupResult old=SpeedPiAntiWindup_Apply(previous,candidate,p,
            iq_limit,integral_limit,release);
        admitted=old.integral_A; limited=old.limited;
    } else {
        previous=clamp(previous,integral_limit);
        candidate=clamp(candidate,integral_limit);
        float raw=(p+candidate)+ff;
        float ref=clamp(raw,iq_limit);
        admitted=candidate;
        if (!release) {
            if (candidate>previous && raw>ref) {
                float boundary=(iq_limit-ff)-p;
                admitted=boundary>previous ? fminf(candidate,boundary) : previous;
            } else if (candidate<previous && raw<ref) {
                float boundary=(-iq_limit-ff)-p;
                admitted=boundary<previous ? fmaxf(candidate,boundary) : previous;
            }
        }
        limited=(uint8_t)(admitted!=candidate);
    }
    float pi=p+admitted;
    float raw=pi+ff;
    float ref=clamp(raw,iq_limit);
    /* Count boundary admission too: float rounding can leave the admitted
     * command one ULP inside the limit after a combined PI+FF saturation.
     * This is evidence only, not a new controller branch. */
    return (SpeedAccelFfResult){admitted,pi,ff,raw,ref,
        (uint8_t)(raw!=ref || fabsf(ref)>=iq_limit || limited),limited};
}

void SpeedAccelFf_StatsReset(SpeedAccelFfStats *s)
{ *s=(SpeedAccelFfStats){0}; s->settling_time_s=-1.0f; }

void SpeedAccelFf_Observe(SpeedAccelFfStats *s,const SpeedAccelFfFrame *f,float dt_s)
{
    if (!f->valid || !isfinite(dt_s) || dt_s<=0) return;
    if (!s->samples || f->command_rpm!=s->command_rpm) {
        ++s->segment; s->command_rpm=f->command_rpm;
        if (f->command_rpm!=0) s->direction=f->command_rpm>0 ? 1.0f : -1.0f;
        s->segment_time_s=0; s->settling=0; s->settled=0; s->settling_time_s=-1;
    }
    ++s->samples; s->time_s+=dt_s; s->segment_time_s+=dt_s;
    float error=fabsf(f->speed_ref_rpm-f->speed_meas_rpm);
    s->max_error_rpm=fmaxf(s->max_error_rpm,error);
    float phase=f->speed_ref_rpm*f->accel_ref_rpm_s;
    if (phase>0) { s->accel_time_s+=dt_s; s->accel_error_integral+=error*dt_s; }
    else if (phase<0) { s->decel_time_s+=dt_s; s->decel_error_integral+=error*dt_s; }
    float overshoot=s->direction*(f->speed_meas_rpm-f->command_rpm);
    if (f->command_rpm==0) overshoot=-s->direction*f->speed_meas_rpm;
    if (fabsf(f->speed_ref_rpm-f->command_rpm)<=0.001f)
        s->overshoot_rpm=fmaxf(s->overshoot_rpm,overshoot);
    s->iq_peak_a=fmaxf(s->iq_peak_a,fabsf(f->iq_ref_a));
    s->iq_measured_peak_a=fmaxf(s->iq_measured_peak_a,fabsf(f->iq_meas_a));
    s->integrator_peak_a=fmaxf(s->integrator_peak_a,fabsf(f->speed_integrator_a));
    if (f->saturated) {
        s->saturation_s+=dt_s; s->saturation_run_s+=dt_s;
        s->saturation_run_max_s=fmaxf(s->saturation_run_max_s,s->saturation_run_s);
    } else s->saturation_run_s=0;
    float band=fmaxf(SPEED_ACCEL_FF_SETTLE_MIN_RPM,
                    SPEED_ACCEL_FF_SETTLE_RATIO*fabsf(f->command_rpm));
    int inside=fabsf(f->speed_ref_rpm-f->command_rpm)<=0.001f &&
        fabsf(f->speed_meas_rpm-f->command_rpm)<=band;
    if (!inside) { s->settling=0; s->settled=0; s->settling_time_s=-1; }
    else {
        if (!s->settling) { s->settling=1; s->settle_candidate_s=s->segment_time_s; }
        if (s->segment_time_s-s->settle_candidate_s>=SPEED_ACCEL_FF_SETTLE_DWELL_S) {
            s->settled=1; s->settling_time_s=s->settle_candidate_s;
        }
    }
}
