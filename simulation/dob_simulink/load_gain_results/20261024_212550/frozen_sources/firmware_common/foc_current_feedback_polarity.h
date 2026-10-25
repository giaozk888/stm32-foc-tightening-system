#ifndef FOC_CURRENT_FEEDBACK_POLARITY_H
#define FOC_CURRENT_FEEDBACK_POLARITY_H
#include <stdint.h>

/* Sign of (ADC raw - calibrated zero) in the CONTROL feedback convention.
 * -1 preserves the existing low-side phase-current convention. The manual's
 * positive shunt-current voltage alone does not establish motor phase sign.
 * +1 is an unqualified comparison, never a runtime switch or motor admission.
 * Raw protection/trace counts deliberately retain their existing convention. */
#ifndef FOC_CURRENT_FEEDBACK_SIGN
#define FOC_CURRENT_FEEDBACK_SIGN (-1)
#endif
#if FOC_CURRENT_FEEDBACK_SIGN != -1 && FOC_CURRENT_FEEDBACK_SIGN != 1
#error FOC_CURRENT_FEEDBACK_SIGN must be -1 or 1
#endif
#if FOC_CURRENT_FEEDBACK_SIGN == 1
#if !defined(FOC_FAST_REJECT_COMPUTE_ONLY) || FOC_FAST_REJECT_COMPUTE_ONLY != 1
#error Unqualified current polarity requires power-hard-off compute-only firmware
#endif
#endif

static inline float FocCurrentFeedback_FromRaw(uint16_t raw, uint16_t zero,
                                               float count_to_A)
{
#if FOC_CURRENT_FEEDBACK_SIGN == 1
    return ((int32_t)raw - (int32_t)zero) * count_to_A;
#else
    return ((int32_t)zero - (int32_t)raw) * count_to_A;
#endif
}
#endif
