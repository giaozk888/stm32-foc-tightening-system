#ifndef SPEED_PI_ANTI_WINDUP_H
#define SPEED_PI_ANTI_WINDUP_H
#include <stdint.h>

#if defined(FOC_SPEED_PI_ANTI_WINDUP) && (!defined(FOC_SPEED_BRAKE_TRACK) || \
    !defined(FOC_ADC_COUNTS_100_40_CANDIDATE))
#error Speed anti-windup requires the separate protected SB3 100/40 A candidate
#endif
#if defined(FOC_SPEED_SB3_DISABLE_CANDIDATE) && !defined(FOC_SPEED_PI_ANTI_WINDUP) && \
    !defined(FOC_SPEED_LEGACY_AW_COMPARE)
#error SB3-off comparison requires speed anti-windup
#endif

typedef struct {
    float integral_A,current_A;
    uint8_t limited;
} SpeedPiAntiWindupResult;

/* Conditional integration with partial admission at the current boundary.
 * Finite inputs/positive limits are the existing controller's contract.
 * No new gain, filter, reset state, saved torque or physical-Iq feedback.
 * A mandatory bleed/unload must not be vetoed by an actuator constraint.
 * SB3 still runs AFTER this function unless the explicit SB3-off comparison
 * is selected. Independent overspeed/overcurrent fault owners never change.
 */
static inline SpeedPiAntiWindupResult SpeedPiAntiWindup_Apply(
    float previous,float candidate,float p_term,float current_limit,
    float integral_limit,uint8_t force_release)
{
    previous=previous < -integral_limit ? -integral_limit :
             previous > integral_limit ? integral_limit : previous;
    candidate=candidate < -integral_limit ? -integral_limit :
              candidate > integral_limit ? integral_limit : candidate;
    float admitted=candidate;
    if (!force_release) {
        if (candidate>previous && p_term+candidate>current_limit) {
            float boundary=current_limit-p_term;
            admitted=boundary>previous ? boundary : previous;
        } else if (candidate<previous && p_term+candidate < -current_limit) {
            float boundary=-current_limit-p_term;
            admitted=boundary<previous ? boundary : previous;
        }
    }
    /* Recompute from the committed I, not a rejected tentative integral. */
    float command=p_term+admitted;
    command=command < -current_limit ? -current_limit :
            command > current_limit ? current_limit : command;
    return (SpeedPiAntiWindupResult){admitted,command,(uint8_t)(admitted!=candidate)};
}
#endif
