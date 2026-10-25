#ifndef FOC_CURRENT_MEDIAN_H
#define FOC_CURRENT_MEDIAN_H
#include <stdint.h>
#include "foc_hot_path.h"
#include "foc_current_spike.h"
#include "foc_current_trend4.h"
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
#if !defined(FOC_PROTECTED_CLOSED_LOOP) || !defined(FOC_CURRENT_TREND4)
#error Adaptive filter requires the separate protected hard-off experiment
#endif
#include "foc_current_adaptive.h"
#endif

#if defined(FOC_CURRENT_TREND4)
#if !defined(FOC_CURRENT_SPIKE_ONLY)
#error Four-point selection requires the output-locked spike profile
#endif
#define FOC_CURRENT_HISTORY_PAIRS 4U
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
#define FOC_CURRENT_FILTER_FIELDS "MEDIAN=0 SPIKE3=0 TREND4=1 ADAPT=1 DELAY_PAIRS=1 FILTER_REV=4 "
#define FOC_CURRENT_FILTER_NAME "adaptive-trend4-20-40-quiet10"
#else
#define FOC_CURRENT_FILTER_FIELDS "MEDIAN=0 SPIKE3=0 TREND4=1 DELAY_PAIRS=1 FILTER_REV=3 "
#define FOC_CURRENT_FILTER_NAME "isolated-trend4-30-40-mean"
#endif
#elif defined(FOC_CURRENT_SPIKE_ONLY)
#define FOC_CURRENT_HISTORY_PAIRS 3U
#define FOC_CURRENT_FILTER_FIELDS "MEDIAN=0 SPIKE3=1 DELAY_PAIRS=1 FILTER_REV=2 "
#define FOC_CURRENT_FILTER_NAME "isolated-spike3-dual10-40-mean"
#else
#define FOC_CURRENT_HISTORY_PAIRS 3U
#define FOC_CURRENT_FILTER_FIELDS "MEDIAN=1 "
#define FOC_CURRENT_FILTER_NAME "median3"
#endif

/* Fixed work and storage: no allocation, sorting loop, or peripheral calls. */
static inline uint16_t FocMedian3_U16(uint16_t a, uint16_t b, uint16_t c)
{
    uint16_t t;
    if (a > b) { t = a; a = b; b = t; }
    if (b > c) { t = b; b = c; c = t; }
    if (a > b) { t = a; a = b; b = t; }
    return b;
}

typedef struct {
    uint16_t u[FOC_CURRENT_HISTORY_PAIRS], v[FOC_CURRENT_HISTORY_PAIRS];
    uint8_t index, count;
    uint8_t last_spike_mask; /* 1=U, 2=V; explicit invalid-center evidence. */
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
    FocAdaptiveNoise noise[2];
#endif
} FocCurrentMedian;

static inline void FocCurrentMedian_Begin(FocCurrentMedian *m)
{
    *m = (FocCurrentMedian){0};
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
    FocAdaptive_Begin(&m->noise[0]); FocAdaptive_Begin(&m->noise[1]);
#endif
}

/* Feed every PHYSICAL pair, even rejected pairs. Never compress time by
 * joining accepted samples separated by an unknown interval. First H-1
 * pairs warm the history and cannot qualify a calibration sample. */
FOC_HOT_INLINE int FocCurrentMedian_Push(FocCurrentMedian *m,
                                       uint16_t u, uint16_t v,
                                       uint16_t *filtered_u, uint16_t *filtered_v)
{
    m->u[m->index] = u; m->v[m->index] = v;
    m->index = (uint8_t)((m->index + 1U) % FOC_CURRENT_HISTORY_PAIRS);
    if (m->count < FOC_CURRENT_HISTORY_PAIRS) ++m->count;
    m->last_spike_mask = 0U;
    if (m->count < FOC_CURRENT_HISTORY_PAIRS) return 0;
#if defined(FOC_CURRENT_TREND4)
    uint8_t p=m->index, a=(uint8_t)((p+1U)%4U);
    uint8_t b=(uint8_t)((p+2U)%4U), c=(uint8_t)((p+3U)%4U);
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
    FocAdaptiveWindow wu=FocAdaptive_Analyze(&m->noise[0],m->u[p],m->u[a],m->u[b],m->u[c]);
    FocAdaptiveWindow wv=FocAdaptive_Analyze(&m->noise[1],m->v[p],m->v[a],m->v[b],m->v[c]);
    m->last_spike_mask = wu.isolated | (uint8_t)(wv.isolated << 1U);
    /* Defer both estimators until BOTH classifications are known. A repair
     * on either channel must still reset quiet learning on both channels. */
    FocAdaptive_LearnWindow(&m->noise[0],wu,m->last_spike_mask);
    FocAdaptive_LearnWindow(&m->noise[1],wv,m->last_spike_mask);
#else
    m->last_spike_mask = FocTrend4_Isolated(m->u[p],m->u[a],m->u[b],m->u[c]) |
        (uint8_t)(FocTrend4_Isolated(m->v[p],m->v[a],m->v[b],m->v[c]) << 1U);
#endif
#if defined(FOC_PAIR_FAST_PATH) || (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
    /* Reuse the exact classification, including invalid input handling.
     * Do not reclassify the same four samples inside Select(). */
    *filtered_u = (m->last_spike_mask & 1U) ?
        (uint16_t)(((uint32_t)m->u[a]+m->u[c]+1U)/2U) : m->u[b];
    *filtered_v = (m->last_spike_mask & 2U) ?
        (uint16_t)(((uint32_t)m->v[a]+m->v[c]+1U)/2U) : m->v[b];
#else
    *filtered_u = FocTrend4_Select(m->u[p],m->u[a],m->u[b],m->u[c]);
    *filtered_v = FocTrend4_Select(m->v[p],m->v[a],m->v[b],m->v[c]);
#endif
#elif defined(FOC_CURRENT_SPIKE_ONLY)
    /* index points at oldest after every push, NOT the center. Keep
     * chronological neighbors even when a preceding center was rejected. */
    uint8_t a = m->index, b = (uint8_t)((a+1U)%3U), c = (uint8_t)((a+2U)%3U);
    m->last_spike_mask = FocSpike3_Isolated(m->u[a],m->u[b],m->u[c]) |
        (uint8_t)(FocSpike3_Isolated(m->v[a],m->v[b],m->v[c]) << 1U);
    *filtered_u = FocSpike3_Select(m->u[a],m->u[b],m->u[c]);
    *filtered_v = FocSpike3_Select(m->v[a],m->v[b],m->v[c]);
#else
    *filtered_u = FocMedian3_U16(m->u[0], m->u[1], m->u[2]);
    *filtered_v = FocMedian3_U16(m->v[0], m->v[1], m->v[2]);
#endif
    return 1;
}

/* PWM-on startup admission keeps the existing RAW deviation gate intact.
 * Either filter is never a reason to accept an out-of-range raw pair.
 * Return -1 rejected, 0 warming, 1 accepted; accumulation is caller-owned. */
static inline int FocRunZeroMedian_Push(FocCurrentMedian *m,
                                       uint16_t u, uint16_t v,
                                       uint16_t zero_u, uint16_t zero_v,
                                       int32_t limit,
                                       uint16_t *filtered_u, uint16_t *filtered_v)
{
    int ready = FocCurrentMedian_Push(m, u, v, filtered_u, filtered_v);
    int32_t du = (int32_t)u - zero_u, dv = (int32_t)v - zero_v;
    if (limit < 0 || u > 4095U || v > 4095U ||
        du < -limit || du > limit || dv < -limit || dv > limit) return -1;
    if (!ready) return 0;
    du = (int32_t)*filtered_u - zero_u;
    dv = (int32_t)*filtered_v - zero_v;
    return (du < -limit || du > limit || dv < -limit || dv > limit) ? -1 : 1;
}
#endif
