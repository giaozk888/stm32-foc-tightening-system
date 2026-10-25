#include "speed_scurve.h"
#include <math.h>

enum { SC_IDLE, SC_RELEASE, SC_RISE, SC_HOLD, SC_FALL };

void SpeedScurve_Reset(SpeedScurve *s, float reference_rpm)
{
    *s = (SpeedScurve){0};
    s->speed_rpm = s->target_rpm = reference_rpm;
}

/* Plan from zero acceleration: jerk up, optional constant acceleration,
 * jerk down. Short moves are triangular in acceleration, not clipped steps. */
static void plan(SpeedScurve *s)
{
    float delta = s->target_rpm - s->speed_rpm;
    float distance = fabsf(delta);
    if (distance == 0.0f) {
        s->phase = SC_IDLE;
        return;
    }
    s->jerk_rpm_s2 = delta > 0.0f ? SPEED_SCURVE_MAX_JERK_RPM_S2 :
                                                  -SPEED_SCURVE_MAX_JERK_RPM_S2;
    s->ramp_s = fminf(sqrtf(distance / SPEED_SCURVE_MAX_JERK_RPM_S2),
                    SPEED_SCURVE_MAX_ACCEL_RPM_S / SPEED_SCURVE_MAX_JERK_RPM_S2);
    s->hold_s = fmaxf(0.0f, distance /
                    (SPEED_SCURVE_MAX_JERK_RPM_S2 * s->ramp_s) - s->ramp_s);
    s->remaining_s = s->ramp_s;
    s->phase = SC_RISE;
}

float SpeedScurve_Step(SpeedScurve *s, float target_rpm, float dt_s)
{
    if (!isfinite(target_rpm) || !isfinite(dt_s) || dt_s <= 0.0f)
        return s->speed_rpm;
    if (target_rpm != s->target_rpm) {
        s->target_rpm = target_rpm;
        /* Preserve speed AND acceleration on retarget/reversal. First release
         * existing acceleration at bounded jerk, then plan to the latest target.
         * A new target inside stopping distance can be crossed transiently;
         * it is not achieved by discontinuously clipping reference/acceleration. */
        if (s->acceleration_rpm_s != 0.0f) {
            s->remaining_s = fabsf(s->acceleration_rpm_s) / SPEED_SCURVE_MAX_JERK_RPM_S2;
            s->jerk_rpm_s2 = s->acceleration_rpm_s > 0.0f ?
                -SPEED_SCURVE_MAX_JERK_RPM_S2 : SPEED_SCURVE_MAX_JERK_RPM_S2;
            s->phase = SC_RELEASE;
        } else {
            plan(s);
        }
    }
    /* At most release + rise + hold + fall; bounded work, no tick-sized loop. */
    for (unsigned n = 0U; n < 4U && dt_s > 0.0f && s->phase != SC_IDLE; ++n) {
        float h = fminf(dt_s, s->remaining_s);
        s->speed_rpm += (s->acceleration_rpm_s + 0.5f * s->jerk_rpm_s2 * h) * h;
        s->acceleration_rpm_s += s->jerk_rpm_s2 * h;
        dt_s -= h;
        s->remaining_s -= h;
        if (s->remaining_s > 0.0f) break;
        if (s->phase == SC_RELEASE) {
            s->acceleration_rpm_s = 0.0f;
            plan(s);
        } else if (s->phase == SC_RISE && s->hold_s > 0.0f) {
            s->phase = SC_HOLD;
            s->remaining_s = s->hold_s;
            s->jerk_rpm_s2 = 0.0f;
        } else if (s->phase == SC_RISE || s->phase == SC_HOLD) {
            s->phase = SC_FALL;
            s->remaining_s = s->ramp_s;
            s->jerk_rpm_s2 = s->acceleration_rpm_s > 0.0f ?
                -SPEED_SCURVE_MAX_JERK_RPM_S2 : SPEED_SCURVE_MAX_JERK_RPM_S2;
        } else {
            s->speed_rpm = s->target_rpm;
            s->acceleration_rpm_s = 0.0f;
            s->phase = SC_IDLE;
        }
    }
    return s->speed_rpm;
}
