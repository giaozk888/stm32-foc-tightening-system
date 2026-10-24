#ifndef DOB_CONTACT20_OBSERVE10_H
#define DOB_CONTACT20_OBSERVE10_H
#include <math.h>
#include <stdint.h>
#if !defined(FOC_DOB_NORMAL_CONTROL) || !defined(FOC_DOB_CONTACT20_OBSERVE10)
#error CONTACT20/observe10 is exclusive to the opt-in normal DOB A candidate
#endif
/* Process recipe / model admission, NOT hardware safety thresholds. */
#define DOB_CONTACT20_RPM 20U
#define DOB_OBSERVE10_MIN_RAD_S 1.0471975511965977f
#define DOB_FRESH_FEEDBACK_MIN_RAD_S 2.0943951023931953f
/* Observation extends to10rpm only. Below the original20rpm fresh-feedback
 * boundary keep the existing invalid-source hold/fade/expiry, never feed a
 * newly qualified low-speed estimate into the current summing junction. */
static inline uint8_t DobObserve10_FeedbackSpeedQualified(float omega_rad_s)
{
    return (uint8_t)(isfinite(omega_rad_s)&&fabsf(omega_rad_s)>=DOB_FRESH_FEEDBACK_MIN_RAD_S);
}
#endif
