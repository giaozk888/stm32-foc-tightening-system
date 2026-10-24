#include "speed_friction_compensation.h"
#include <math.h>
static float clamp(float v,float limit)
{ return v < -limit ? -limit : v > limit ? limit : v; }

SpeedFrictionResult SpeedFriction_Apply(float previous,float candidate,float p,
    float accel_ref,float ka,float speed_ref,float friction_a,float deadband,
    float iq_limit,float integral_limit,uint8_t release,uint8_t accel_enabled,uint8_t enabled)
{
    float fric=0;
    if (enabled && fabsf(speed_ref)>deadband)
        fric=speed_ref>0 ? friction_a : -friction_a;
    if (fric==0) {
        /* FRIC OFF/deadband: preserve the entire existing AF1 result exactly. */
        return (SpeedFrictionResult){SpeedAccelFf_Apply(previous,candidate,p,accel_ref,
            ka,iq_limit,integral_limit,release,accel_enabled),0};
    }
    float acc_ff=accel_enabled ? ka*accel_ref : 0;
    previous=clamp(previous,integral_limit); candidate=clamp(candidate,integral_limit);
    float raw=((p+candidate)+acc_ff)+fric;
    float ref=clamp(raw,iq_limit);
    float admitted=candidate;
    if (!release) {
        if (candidate>previous && raw>ref) {
            float boundary=((iq_limit-fric)-acc_ff)-p;
            admitted=boundary>previous ? fminf(candidate,boundary) : previous;
        } else if (candidate<previous && raw<ref) {
            float boundary=((-iq_limit-fric)-acc_ff)-p;
            admitted=boundary<previous ? fmaxf(candidate,boundary) : previous;
        }
    }
    uint8_t limited=(uint8_t)(admitted!=candidate);
    float pi=p+admitted;
    raw=(pi+acc_ff)+fric; ref=clamp(raw,iq_limit);
    return (SpeedFrictionResult){{admitted,pi,acc_ff,raw,ref,
        (uint8_t)(raw!=ref || fabsf(ref)>=iq_limit || limited),limited},fric};
}

void SpeedFriction_StatsReset(SpeedFrictionStats *s)
{
    *s=(SpeedFrictionStats){0};
    s->positive.start_delay_s=s->negative.start_delay_s=-1;
}
void SpeedFriction_Observe(SpeedFrictionStats *s,const SpeedFrictionFrame *frame,float dt)
{
    const SpeedAccelFfFrame *f=&frame->control;
    if (!f->valid || !isfinite(dt) || dt<=0) return;
    if (f->command_rpm==0) {
        s->initialized=0; s->moving=0; s->motion_good_s=0;
        return; /* No zero-target direction aggregate; next start is fresh. */
    }
    SpeedFrictionDirectionStats *d=f->command_rpm>0 ? &s->positive : &s->negative;
    float direction=f->command_rpm>0 ? 1.0f : -1.0f;
    if (!s->initialized || f->command_rpm!=s->command_rpm) {
        s->initialized=1; s->command_rpm=f->command_rpm;
        s->segment_elapsed_s=0; s->motion_good_s=0; s->moving=0;
        d->start_delay_s=-1;
    }
    ++d->samples; d->elapsed_s+=dt; s->segment_elapsed_s+=dt;
    float error=fabsf(f->speed_ref_rpm-f->speed_meas_rpm);
    if (fabsf(f->speed_ref_rpm)>SPEED_FRICTION_DEADBAND_RPM &&
        fabsf(f->speed_ref_rpm)<=SPEED_FRICTION_LOW_SPEED_RPM) {
        d->low_time_s+=dt; d->low_error_integral+=error*dt;
    }
    if (fabsf(f->speed_ref_rpm-f->command_rpm)<=.001f &&
        fabsf(f->accel_ref_rpm_s)<=.001f) {
        d->cruise_time_s+=dt; d->cruise_error_integral+=error*dt;
    }
    d->integrator_peak_a=fmaxf(d->integrator_peak_a,fabsf(f->speed_integrator_a));
    d->pi_peak_a=fmaxf(d->pi_peak_a,fabsf(f->iq_pi_a));
    d->iq_peak_a=fmaxf(d->iq_peak_a,fabsf(f->iq_ref_a));
    d->iq_measured_peak_a=fmaxf(d->iq_measured_peak_a,fabsf(f->iq_meas_a));
    d->speed_integral+=f->speed_meas_rpm*dt;
    if (direction*f->speed_ref_rpm>SPEED_FRICTION_DEADBAND_RPM &&
        direction*f->speed_meas_rpm < -SPEED_FRICTION_MOTION_RPM)
        d->wrong_direction_time_s+=dt;
    if (!s->moving) {
        if (direction*f->speed_ref_rpm>SPEED_FRICTION_DEADBAND_RPM &&
            direction*f->speed_meas_rpm>=SPEED_FRICTION_MOTION_RPM) s->motion_good_s+=dt;
        else s->motion_good_s=0;
        if (s->motion_good_s>=SPEED_FRICTION_MOTION_CONFIRM_S) {
            s->moving=1;
            d->start_delay_s=fmaxf(0,s->segment_elapsed_s-s->motion_good_s);
        }
    }
}
