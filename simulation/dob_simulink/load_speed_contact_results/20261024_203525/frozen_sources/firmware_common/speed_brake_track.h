#ifndef SPEED_BRAKE_TRACK_H
#define SPEED_BRAKE_TRACK_H
#include <math.h>
#include <stdint.h>
#if defined(FOC_SPEED_BRAKE_TRACK) && (!defined(FOC_SPEED_BUMPLESS) || \
    !defined(FOC_VOLTAGE_X2_TRIAL) || !defined(FOC_PWM_PIPELINE_CLOSED_LOOP))
#error SB3 requires the complete protected SB2 voltage-comparison profile
#endif

/* SPEED-only command ceiling, NOT an overspeed fault or a speed observer.
 * The normal speed filter/P term are unchanged. Two successive accepted
 * encoder speed deltas can revoke driving torque before the 20ms LPF catches
 * up. The existing Kp and error boundary set braking strength. This does not
 * prove that the inverter/current loop can produce the requested braking.
 */
typedef struct {
    float previous_instant_rpm;
    int8_t direction;
    uint8_t have_previous;
} SpeedBrakeTrack;
typedef struct {
    float current_A,integral_A,brake_speed_rpm;
    uint8_t limited;
} SpeedBrakeTrackResult;

static inline void SpeedBrakeTrack_Reset(SpeedBrakeTrack *s)
{ *s=(SpeedBrakeTrack){0}; }

static inline SpeedBrakeTrackResult SpeedBrakeTrack_Apply(SpeedBrakeTrack *s,
    float reference,float filtered,float instant,float p_term,float integral,
    float current,float kp,float error_boundary,float min_speed,
    float current_limit,float integral_limit)
{
    SpeedBrakeTrackResult out={current,integral,filtered,0U};
    if (!isfinite(reference) || !isfinite(filtered) || !isfinite(instant) ||
        !isfinite(p_term) || !isfinite(integral) || !isfinite(current) ||
        !isfinite(kp) || !(kp>0) || !isfinite(error_boundary) || !(error_boundary>0) ||
        !isfinite(min_speed) || !(min_speed>0) ||
        !isfinite(current_limit) || !(current_limit>0) ||
        !isfinite(integral_limit) || !(integral_limit>0)) {
        SpeedBrakeTrack_Reset(s); return out; /* Existing fault owner unchanged. */
    }
    /* A zero/reversed reference cannot inherit the preceding direction's
     * consecutive-sample history. No latched torque or saved integral. */
    int8_t direction=reference>0 ? 1 : reference<0 ? -1 : 0;
    if (!direction) { SpeedBrakeTrack_Reset(s); return out; }
    if (direction!=s->direction) SpeedBrakeTrack_Reset(s);
    float speed=(float)direction*filtered;
    float fast=(float)direction*instant;
    if (s->have_previous) {
        float previous=(float)direction*s->previous_instant_rpm;
        float two=fast<previous ? fast : previous;
        if (two>speed) speed=two;
    }
    s->previous_instant_rpm=instant; s->direction=direction; s->have_previous=1U;
    out.brake_speed_rpm=(float)direction*speed;
    float target=(float)direction*reference;
    if (speed>=min_speed && speed-target>=error_boundary) {
        float ceiling=kp*(target-speed); /* Negative in the motion direction. */
        if (ceiling < -current_limit) ceiling=-current_limit;
        if ((float)direction*current>ceiling) {
            out.current_A=(float)direction*ceiling;
            /* Track what is actually REQUESTED, never the pre-limiter I.
             * Preserve the existing independent integral clamp. */
            float tracked=out.current_A-p_term;
            out.integral_A=tracked < -integral_limit ? -integral_limit :
                           tracked > integral_limit ? integral_limit : tracked;
            out.limited=1U;
        }
    }
    return out;
}
#endif
