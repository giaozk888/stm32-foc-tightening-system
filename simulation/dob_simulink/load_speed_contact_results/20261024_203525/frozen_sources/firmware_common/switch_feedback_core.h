#ifndef SWITCH_FEEDBACK_CORE_H
#define SWITCH_FEEDBACK_CORE_H
#include "foc_current_median.h"
#include "foc_current_trend4.h"
#include <limits.h>

/* Diagnostic only. No PI, allocation, calibration publication or unlock. */
#define SWITCH_FEEDBACK_PAIRS 3600U /* 180 ms at the pinned 20 kHz trigger. */
enum { SWITCH_OFF = 1, SWITCH_PWM = 2, SWITCH_BRIDGE = 3, SWITCH_GUARD = 4,
       SWITCH_FILTERED_BRIDGE = 5, SWITCH_FILTERED_GUARD = 6 };
enum { SWITCH_DONE = 1, SWITCH_TIME = 2, SWITCH_PAIR = 3,
       SWITCH_CONFIG = 4, SWITCH_RAW_CURRENT = 5, SWITCH_STALE = 6,
       SWITCH_ABORT = 7, SWITCH_ADC_ERROR = 8, SWITCH_CORE_FAULT = 9,
       SWITCH_FILTERED_TRIP = 10, SWITCH_WORK_LATE = 11 };
typedef struct {
    FocCurrentMedian median;
    uint32_t count, filtered_count, sum_u, sum_v, filtered_sum_u, filtered_sum_v;
    uint32_t outside, steps, reject_streak, max_reject_streak;
    uint16_t min_u, max_u, min_v, max_v, fmin_u, fmax_u, fmin_v, fmax_v;
    uint16_t last_u, last_v, zero_u, zero_v, raw_limit;
    uint16_t first_bad_u, first_bad_v;
    uint32_t first_bad_pair;
    /* Observer only: never participates in admission, trip or calibration. */
    uint16_t trend_history[4][2];
    uint32_t trend_count, trend_sum_u, trend_sum_v, trend_repairs_u, trend_repairs_v;
    uint16_t trend_min_u, trend_max_u, trend_min_v, trend_max_v;
    uint8_t mode;
} SwitchFeedbackStats;

static inline void SwitchFeedback_Begin(SwitchFeedbackStats *s, uint8_t mode,
                                        uint16_t u0, uint16_t v0, uint16_t limit)
{
    *s = (SwitchFeedbackStats){0};
    s->min_u = s->min_v = s->fmin_u = s->fmin_v = UINT16_MAX;
    s->trend_min_u = s->trend_min_v = UINT16_MAX;
    s->mode = mode; s->zero_u = u0; s->zero_v = v0; s->raw_limit = limit;
}
static inline uint32_t SwitchFeedback_Abs(int32_t n)
{ return (uint32_t)(n < 0 ? -n : n); }
static inline void SwitchFeedback_Range(uint16_t x, uint16_t *lo, uint16_t *hi)
{ if (x < *lo) *lo = x; if (x > *hi) *hi = x; }

/* Raw checks run BEFORE median. Reconstructed W gets the same 4 A gate.
 * OFF/PWM record raw defects; BRIDGE stops on the first raw current trip.
 * The unchanged 60-count/20-consecutive step gate is never median-bypassed. */
static inline uint8_t SwitchFeedback_Push(SwitchFeedbackStats *s, uint16_t u, uint16_t v)
{
    uint16_t fu = 0, fv = 0;
    int32_t du = (int32_t)u - s->zero_u, dv = (int32_t)v - s->zero_v;
    if (s->count >= SWITCH_FEEDBACK_PAIRS) return SWITCH_CONFIG;
    uint8_t step = s->count &&
        (SwitchFeedback_Abs((int32_t)u - s->last_u) > 60U ||
         SwitchFeedback_Abs((int32_t)v - s->last_v) > 60U);
    s->last_u = u; s->last_v = v;
    ++s->count; s->sum_u += u; s->sum_v += v;
    SwitchFeedback_Range(u, &s->min_u, &s->max_u);
    SwitchFeedback_Range(v, &s->min_v, &s->max_v);
    if (step) { ++s->steps; ++s->reject_streak; }
    else s->reject_streak = 0U;
    if (s->reject_streak > s->max_reject_streak) s->max_reject_streak = s->reject_streak;
    if (SwitchFeedback_Abs(du) > 100U || SwitchFeedback_Abs(dv) > 100U) ++s->outside;
    uint8_t trip = u > 4095U || v > 4095U || !s->raw_limit ||
        SwitchFeedback_Abs(du) > s->raw_limit || SwitchFeedback_Abs(dv) > s->raw_limit ||
        SwitchFeedback_Abs(du + dv) > s->raw_limit;
    if (trip && !s->first_bad_pair) {
        s->first_bad_pair = s->count; s->first_bad_u = u; s->first_bad_v = v;
    }
    if (FocCurrentMedian_Push(&s->median, u, v, &fu, &fv)) {
        ++s->filtered_count; s->filtered_sum_u += fu; s->filtered_sum_v += fv;
        SwitchFeedback_Range(fu, &s->fmin_u, &s->fmax_u);
        SwitchFeedback_Range(fv, &s->fmin_v, &s->fmax_v);
    }
    for (unsigned i = 0; i < 3U; ++i) {
        s->trend_history[i][0] = s->trend_history[i+1U][0];
        s->trend_history[i][1] = s->trend_history[i+1U][1];
    }
    s->trend_history[3][0] = u; s->trend_history[3][1] = v;
    if (s->count >= 4U) {
        fu = FocTrend4_Select(s->trend_history[0][0], s->trend_history[1][0],
                             s->trend_history[2][0], s->trend_history[3][0]);
        fv = FocTrend4_Select(s->trend_history[0][1], s->trend_history[1][1],
                             s->trend_history[2][1], s->trend_history[3][1]);
        ++s->trend_count; s->trend_sum_u += fu; s->trend_sum_v += fv;
        s->trend_repairs_u += fu != s->trend_history[2][0];
        s->trend_repairs_v += fv != s->trend_history[2][1];
        SwitchFeedback_Range(fu, &s->trend_min_u, &s->trend_max_u);
        SwitchFeedback_Range(fv, &s->trend_min_v, &s->trend_max_v);
    }
    if (s->mode == SWITCH_BRIDGE && trip) return SWITCH_RAW_CURRENT;
    if (s->mode == SWITCH_BRIDGE && s->reject_streak >= 20U) return SWITCH_STALE;
    return s->count == SWITCH_FEEDBACK_PAIRS ? SWITCH_DONE : 0U;
}
#endif
