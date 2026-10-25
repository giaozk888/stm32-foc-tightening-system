#include "foc_current_zero.h"
#include <string.h>

_Static_assert(FOC_ZERO_WINDOW_PAIRS % 2U == 0U, "Two equal drift windows required");
_Static_assert(FOC_ZERO_WINDOW_PAIRS <= UINT32_MAX / 4095U, "Sum must not overflow");

void FocZero_Begin(FocZeroCal *c, uint16_t nominal)
{
    memset(c, 0, sizeof(*c)); /* Only before IRQ/start, never from Push. */
    c->nominal = nominal;
    c->state = FOC_ZERO_SETTLING;
    c->observed_min_u = c->observed_min_v = UINT16_MAX;
    if (nominal < 1000U || nominal > 2200U)
        FocZero_Abort(c, FOC_ZERO_BAD_CONFIG);
}

void FocZero_Abort(FocZeroCal *c, FocZeroReason reason)
{
    c->state = FOC_ZERO_FAILED;
    c->reason = reason;
    c->zero_u = c->zero_v = 0U; /* Never publish partial/failed averages. */
}

static void RestartWindow(FocZeroCal *c)
{
    c->count = c->sum_u = c->sum_v = c->first_u = c->first_v = 0U;
    if (++c->restarts >= FOC_ZERO_MAX_RESTARTS)
        FocZero_Abort(c, FOC_ZERO_UNSTABLE);
}

void FocZero_Push(FocZeroCal *c, uint16_t u, uint16_t v)
{
    if (c->state != FOC_ZERO_SETTLING && c->state != FOC_ZERO_COLLECTING)
        return;
    ++c->total;
    c->last_u = u; c->last_v = v;
    if (u < c->observed_min_u) c->observed_min_u = u;
    if (u > c->observed_max_u) c->observed_max_u = u;
    if (v < c->observed_min_v) c->observed_min_v = v;
    if (v > c->observed_max_v) c->observed_max_v = v;
    if (c->state == FOC_ZERO_SETTLING) {
        if (++c->settled >= FOC_ZERO_SETTLE_PAIRS) c->state = FOC_ZERO_COLLECTING;
        return;
    }
    /* The nominal 1.25 V reference bound prevents a quiet but shifted input
     * (or a different analog signal) simply being averaged into a new zero. */
    int32_t du = (int32_t)u - c->nominal;
    int32_t dv = (int32_t)v - c->nominal;
    if (u < 1000U || u > 2200U || v < 1000U || v > 2200U ||
        du < -(int32_t)FOC_ZERO_MAX_NOMINAL_DELTA ||
        du > (int32_t)FOC_ZERO_MAX_NOMINAL_DELTA ||
        dv < -(int32_t)FOC_ZERO_MAX_NOMINAL_DELTA ||
        dv > (int32_t)FOC_ZERO_MAX_NOMINAL_DELTA) {
        FocZero_Abort(c, FOC_ZERO_OUT_OF_RANGE);
        return;
    }
    if (c->count == 0U) {
        c->min_u = c->max_u = u; c->min_v = c->max_v = v;
    } else {
        if (u < c->min_u) c->min_u = u;
        if (u > c->max_u) c->max_u = u;
        if (v < c->min_v) c->min_v = v;
        if (v > c->max_v) c->max_v = v;
    }
    if ((uint32_t)(c->max_u - c->min_u) > FOC_ZERO_MAX_SPAN ||
        (uint32_t)(c->max_v - c->min_v) > FOC_ZERO_MAX_SPAN) {
        ++c->span_restarts;
        RestartWindow(c); /* Discard the WHOLE contaminated window. */
        return;
    }
    c->sum_u += u; c->sum_v += v;
    if (c->count < FOC_ZERO_WINDOW_PAIRS / 2U) {
        c->first_u += u; c->first_v += v;
    }
    if (++c->count != FOC_ZERO_WINDOW_PAIRS) return;
    int32_t drift_u = (int32_t)(c->sum_u - c->first_u) - (int32_t)c->first_u;
    int32_t drift_v = (int32_t)(c->sum_v - c->first_v) - (int32_t)c->first_v;
    const int32_t limit = FOC_ZERO_MAX_HALF_DRIFT * (FOC_ZERO_WINDOW_PAIRS / 2U);
    if (drift_u < -limit || drift_u > limit || drift_v < -limit || drift_v > limit) {
        ++c->drift_restarts;
        RestartWindow(c);
        return;
    }
    c->zero_u = (uint16_t)((c->sum_u + FOC_ZERO_WINDOW_PAIRS / 2U) / FOC_ZERO_WINDOW_PAIRS);
    c->zero_v = (uint16_t)((c->sum_v + FOC_ZERO_WINDOW_PAIRS / 2U) / FOC_ZERO_WINDOW_PAIRS);
    c->state = FOC_ZERO_READY;
}

void FocZero_Snapshot(const FocZeroCal *c, FocZeroCal *snapshot)
{
    *snapshot = *c; /* Caller serializes against the sole ISR writer. */
}
