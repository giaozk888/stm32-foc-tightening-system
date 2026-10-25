#ifndef SPEED_BUMPLESS_H
#define SPEED_BUMPLESS_H
#include "speed_startup_brake.h"
#if defined(FOC_SPEED_BUMPLESS) && (!defined(FOC_SPEED_STARTUP_BRAKE) || \
    !defined(FOC_ZERO_VALID_ADMISSION) || !defined(FOC_LOADED_FSM_TRIAL))
#error SB2 requires the complete protected zero-admission loaded-SPEED profile
#endif

/* Provisional SPEED-only shaping, NOT current/overspeed fault thresholds.
 * At 1 kHz: driving-I change is bounded to +0.4 mA / -10 mA per update.
 * Release 0.24 A in >=24 ms instead of the SB1 single-update reset. Recovery
 * allows the existing Ki*20rpm = 0.4 A/s, never more than the original PI
 * candidate. There is no saved torque feedforward or extra persistent state.
 */
#define SPEED_BUMPLESS_I_RISE_A_PER_S 0.40f
#define SPEED_BUMPLESS_I_RELEASE_A_PER_S 10.0f
enum { SPEED_BUMPLESS_UNLOAD=4U };

static inline SpeedStartupBrakeResult SpeedBumpless_Apply(
    float previous_A,float candidate_A,float reference_rpm,float speed_rpm,
    float dt_s,float overspeed_error_rpm,float overspeed_min_rpm)
{
    SpeedStartupBrakeResult out={candidate_A,0U};
    float error=reference_rpm-speed_rpm;
    if (!(dt_s>0.0f)) {
        out.integral_A=previous_A; return out;
    }
    /* Use PRE-update I, not the already-modified legacy bleed candidate.
     * Only unload I that still drives the current overspeed direction.
     * Stop at zero: no forced opposite torque or new observer is introduced.
     * If speed returns inside the existing error boundary, normal PI resumes
     * from the remaining I, not from a fabricated zero/reloaded torque.
     */
    float step=SPEED_BUMPLESS_I_RELEASE_A_PER_S*dt_s;
    if (speed_rpm>=overspeed_min_rpm && error<=-overspeed_error_rpm && previous_A>0.0f) {
        out.integral_A=previous_A>step ? previous_A-step : 0.0f;
        out.flags=SPEED_BUMPLESS_UNLOAD;
        return out;
    }
    if (speed_rpm<=-overspeed_min_rpm && error>=overspeed_error_rpm && previous_A<0.0f) {
        out.integral_A=previous_A < -step ? previous_A+step : 0.0f;
        out.flags=SPEED_BUMPLESS_UNLOAD;
        return out;
    }
    float rise=SPEED_BUMPLESS_I_RISE_A_PER_S*dt_s;
    if (reference_rpm>0.0f && candidate_A>0.0f) {
        float ceiling=(previous_A>0.0f ? previous_A : 0.0f)+rise;
        if (candidate_A>ceiling) {
            out.integral_A=ceiling; out.flags=SPEED_STARTUP_I_LIMITED;
        }
    } else if (reference_rpm<0.0f && candidate_A<0.0f) {
        float floor=(previous_A<0.0f ? previous_A : 0.0f)-rise;
        if (candidate_A<floor) {
            out.integral_A=floor; out.flags=SPEED_STARTUP_I_LIMITED;
        }
    }
    return out;
}
#endif
