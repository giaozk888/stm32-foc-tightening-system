#include "foc_zero_median.h"
#include "foc_current_median.h"
#include <string.h>
void FocZeroMedian_Begin(FocZeroMedian *m, FocZeroCal *filtered, uint16_t nominal)
{
    memset(m, 0, sizeof(*m));
    m->min_u = m->min_v = UINT16_MAX;
    FocZero_Begin(&m->raw, nominal);
    FocZero_Begin(filtered, nominal);
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
    FocZeroRobust_Begin(&m->robust);
#endif
}
void FocZeroMedian_Push(FocZeroMedian *m, FocZeroCal *filtered, uint16_t u, uint16_t v)
{
    if (filtered->state != FOC_ZERO_SETTLING && filtered->state != FOC_ZERO_COLLECTING)
        return;
    ++m->pairs;
    if (u < m->min_u) m->min_u = u;
    if (u > m->max_u) m->max_u = u;
    if (v < m->min_v) m->min_v = v;
    if (v > m->max_v) m->max_v = v;
    if (m->pairs > FOC_ZERO_SETTLE_PAIRS) {
        ++m->raw_window_pairs;
        int32_t du = (int32_t)u - filtered->nominal;
        int32_t dv = (int32_t)v - filtered->nominal;
        if (du < -FOC_ZERO_MAX_NOMINAL_DELTA || du > FOC_ZERO_MAX_NOMINAL_DELTA ||
            dv < -FOC_ZERO_MAX_NOMINAL_DELTA || dv > FOC_ZERO_MAX_NOMINAL_DELTA)
            ++m->outside_nominal;
    }
    FocZero_Push(&m->raw, u, v); /* First failure remains latched and inspectable. */
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
    FocZeroRobust_Push(&m->robust,filtered,u,v);
    m->changed=m->robust.outliers;
    return;
#else
    m->u[m->index] = u; m->v[m->index] = v;
    m->index = (uint8_t)((m->index + 1U) % FOC_CURRENT_HISTORY_PAIRS);
    uint16_t fu = u, fv = v;
    if (m->pairs >= FOC_CURRENT_HISTORY_PAIRS) {
#if defined(FOC_CURRENT_TREND4)
        uint8_t p=m->index, a=(uint8_t)((p+1U)%4U);
        uint8_t b=(uint8_t)((p+2U)%4U), c=(uint8_t)((p+3U)%4U);
        fu=FocTrend4_Select(m->u[p],m->u[a],m->u[b],m->u[c]);
        fv=FocTrend4_Select(m->v[p],m->v[a],m->v[b],m->v[c]);
        if (FocTrend4_Isolated(m->u[p],m->u[a],m->u[b],m->u[c]) ||
            FocTrend4_Isolated(m->v[p],m->v[a],m->v[b],m->v[c])) ++m->changed;
#elif defined(FOC_CURRENT_SPIKE_ONLY)
        uint8_t a = m->index, b = (uint8_t)((a+1U)%3U), c = (uint8_t)((a+2U)%3U);
        fu = FocSpike3_Select(m->u[a],m->u[b],m->u[c]);
        fv = FocSpike3_Select(m->v[a],m->v[b],m->v[c]);
        if (FocSpike3_Isolated(m->u[a],m->u[b],m->u[c]) ||
            FocSpike3_Isolated(m->v[a],m->v[b],m->v[c])) ++m->changed;
#else
        fu = FocMedian3_U16(m->u[0], m->u[1], m->u[2]);
        fv = FocMedian3_U16(m->v[0], m->v[1], m->v[2]);
        if (fu != u || fv != v) ++m->changed;
#endif
    }
    /* Never convert an invalid 12-bit raw value into an acceptable sample. */
    if (u > 4095U || v > 4095U) {
        FocZero_Abort(filtered, FOC_ZERO_OUT_OF_RANGE);
        return;
    }
#if defined(FOC_CURRENT_SPIKE_ONLY)
    /* Startup pairs are history only: do not duplicate any normal
     * center into calibration. Each later physical pair emits one center. */
    if (m->pairs < FOC_CURRENT_HISTORY_PAIRS) return;
#endif
    FocZero_Push(filtered, fu, fv);
#endif
}
