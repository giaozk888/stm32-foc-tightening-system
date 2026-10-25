#ifndef FOC_RAW_OBSERVE_POLICY_H
#define FOC_RAW_OBSERVE_POLICY_H
#include <stdint.h>
#include <math.h>

/* This is not a motor protection policy. It permits collecting follow-up
 * samples only when the existing fixture physically suppresses all outputs.
 * There is deliberately no console/RPC switch and no normal-build fallback. */
#if !defined(FOC_RAW_OBSERVE_ONLY) || !defined(FOC_CURRENT_TREND4) || \
    !defined(FOC_CURRENT_SPIKE_ONLY) || !defined(FOC_ISOLATED_CONCURRENCY) || \
    !defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY) || defined(ZERO_RETEST_BOOT) || \
    defined(FOC_ZERO_FAILURE_TRACE) || defined(SWITCH_FEEDBACK_DIAGNOSTIC) || \
    defined(FOC_OC_LAYERED_SELFTEST) || defined(TIGHTEN_SYNTHETIC_BENCH)
#error Raw observe-only is restricted to the standalone hard-off Trend4 fixture
#endif

static inline int FocRawObserve_StopRequired(uint16_t u, uint16_t v,
                                            float count_to_A,
                                            float fu, float fv, float fw,
                                            float limit_A, int hard_off)
{
    /* A valid raw overload is recorded by FocOcShadow, not used as feedback.
     * Out-of-range ADC codes and nonfinite feedback are not filterable data. */
    return !hard_off || u > 4095U || v > 4095U ||
           !isfinite(count_to_A) || !(count_to_A > 0.0f) ||
           !isfinite(limit_A) || !(limit_A > 0.0f) ||
           !isfinite(fu) || !isfinite(fv) || !isfinite(fw)
#if !defined(FOC_FILTERED_OBSERVE_ONLY)
           || fabsf(fu) > limit_A || fabsf(fv) > limit_A || fabsf(fw) > limit_A
#endif
           ;
}
#endif
