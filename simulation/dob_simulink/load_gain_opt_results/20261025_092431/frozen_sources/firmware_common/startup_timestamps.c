#include "startup_timestamps.h"
#include <math.h>
_Static_assert(sizeof(StartupTimestamps)==76U,"Startup timestamp RAM ABI");
void StartupTimes_Reset(StartupTimestamps *s) {*s=(StartupTimestamps){0};}
void StartupTimes_Begin(StartupTimestamps *s,uint32_t now_us,float command_rpm)
{
    if (s->valid || !isfinite(command_rpm) || command_rpm==0.0f) return;
    s->t0_us=now_us;s->direction=command_rpm>0.0f ? 1.0f : -1.0f;
    s->valid=START_T0;
}
static void clear_motion(StartupTimestamps *s)
{
    s->forward_samples=0;s->forward_counts=0;s->reverse_counts=0;
    s->motion_direction=0;
}
void StartupTimes_Observe(StartupTimestamps *s,uint32_t now_us,uint32_t sample_us,
    int32_t mechanical_delta_counts,float speed_meas_rpm,float iq_cmd_a)
{
    if (!(s->valid&START_T0)) return;
    ++s->observations;
    if (!(s->valid&START_IQ) && isfinite(iq_cmd_a) && fabsf(iq_cmd_a)>=STARTUP_IQ_THRESHOLD_A) {
        s->t_iq_us=now_us;s->iq_at_event_a=iq_cmd_a;s->valid|=START_IQ;
    }
    if (!(s->valid&START_SPEED) && isfinite(speed_meas_rpm) &&
        fabsf(speed_meas_rpm)>=STARTUP_SPEED_THRESHOLD_RPM) {
        s->t_speed_us=now_us;s->speed_at_event_rpm=speed_meas_rpm;s->valid|=START_SPEED;
    }
    /* Encoder acquisition time shares the 1MHz clock, but predates Task
     * consumption. Never call a pre-command or duplicated sample motion. */
    if ((int32_t)(sample_us-s->t0_us)<0) return;
    if (s->sample_valid && (int32_t)(sample_us-s->last_sample_us)<=0) return;
    if (s->sample_valid && sample_us-s->last_sample_us>STARTUP_MOTION_WINDOW_US) clear_motion(s);
    s->last_sample_us=sample_us;s->sample_valid=1U;
    if (s->valid&START_MOTION) return;
    if (s->forward_samples && sample_us-s->last_forward_us>STARTUP_MOTION_MAX_FORWARD_GAP_US) clear_motion(s);
    if (s->forward_samples && sample_us-s->candidate_us>STARTUP_MOTION_WINDOW_US) clear_motion(s);
    /* Physical motion may be opposite the request. Record that evidence
     * instead of mislabelling a wrong-direction start as 'no motion'. */
    if (!s->forward_samples && mechanical_delta_counts)
        s->motion_direction=mechanical_delta_counts>0 ? 1 : -1;
    int32_t step=s->motion_direction*mechanical_delta_counts;
    if (step>0) {
        if (!s->forward_samples) s->candidate_us=sample_us;
        s->last_forward_us=sample_us;
        ++s->forward_samples;s->forward_counts+=(uint32_t)step;
    } else if (step<0 && s->forward_samples) {
        s->reverse_counts+=(uint32_t)(-step);
        if (s->reverse_counts>STARTUP_MOTION_REVERSE_TOL_COUNTS) clear_motion(s);
    }
    if (s->forward_samples>=STARTUP_MOTION_MIN_FORWARD_SAMPLES &&
        s->forward_counts>=s->reverse_counts+STARTUP_MOTION_MIN_COUNTS &&
        sample_us-s->candidate_us>=STARTUP_MOTION_CONFIRM_US) {
        s->motion_begin_us=s->candidate_us;
        s->t_motion_us=sample_us;s->valid|=START_MOTION;
    }
}
void StartupTimes_Stable(StartupTimestamps *s,uint32_t now_us)
{
    if ((s->valid&START_T0) && !(s->valid&START_STABLE)) {
        s->t_stable_us=now_us;s->valid|=START_STABLE;
    }
}
