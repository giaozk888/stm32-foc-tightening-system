#ifndef SPEED_STARTUP_BRAKE_H
#define SPEED_STARTUP_BRAKE_H
#include <stdint.h>
#if defined(FOC_SPEED_STARTUP_BRAKE) && (!defined(FOC_LOADED_FSM_TRIAL) || \
    !defined(FOC_PWM_PIPELINE_CLOSED_LOOP))
#error Speed startup/brake candidate requires the protected loaded-FSM profile
#endif

/* Candidate operates in the 1 kHz SPEED outer loop only. The existing PI,
 * output clamps, current loop, encoder filter and all faults remain owners.
 * This is command shaping, not a replacement for overcurrent/overspeed trips.
 */
#define SPEED_STARTUP_I_RISE_A_PER_S 0.20f
enum { SPEED_STARTUP_I_LIMITED=1U, SPEED_STARTUP_I_BRAKE_RESET=2U };
typedef struct {
    float integral_A;
    uint32_t flags;
} SpeedStartupBrakeResult;

static inline SpeedStartupBrakeResult SpeedStartupBrake_Apply(
    float previous_A, float candidate_A, float reference_rpm, float speed_rpm,
    float dt_s, float overspeed_error_rpm, float overspeed_min_rpm)
{
    SpeedStartupBrakeResult out={candidate_A,0U};
    float error=reference_rpm-speed_rpm;
    /* Same error/speed boundaries as the existing overspeed-I bleed. Remove
     * only I that opposes the proportional braking action. Opposite-sign
     * (already braking) I remains under the original anti-windup/clamps. */
    if ((speed_rpm>=overspeed_min_rpm && error<=-overspeed_error_rpm && candidate_A>0.0f) ||
        (speed_rpm<=-overspeed_min_rpm && error>=overspeed_error_rpm && candidate_A<0.0f)) {
        out.integral_A=0.0f;
        out.flags=SPEED_STARTUP_I_BRAKE_RESET;
        return out;
    }
    /* Cap growth into the commanded direction, not unwinding or braking.
     * A held load can still reach the original 0.30 A contact threshold;
     * this is a rise-rate bound, never a permanent low current ceiling. */
    float rise=SPEED_STARTUP_I_RISE_A_PER_S*dt_s;
    if (reference_rpm>0.0f && candidate_A>0.0f) {
        float ceiling=(previous_A>0.0f ? previous_A : 0.0f)+rise;
        if (candidate_A>ceiling) {
            out.integral_A=ceiling;
            out.flags=SPEED_STARTUP_I_LIMITED;
        }
    } else if (reference_rpm<0.0f && candidate_A<0.0f) {
        float floor=(previous_A<0.0f ? previous_A : 0.0f)-rise;
        if (candidate_A<floor) {
            out.integral_A=floor;
            out.flags=SPEED_STARTUP_I_LIMITED;
        }
    }
    return out;
}
#endif
