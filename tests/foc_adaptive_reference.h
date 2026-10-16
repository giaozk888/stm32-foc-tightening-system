#ifndef TESTS_FOC_ADAPTIVE_REFERENCE_H
#define TESTS_FOC_ADAPTIVE_REFERENCE_H
#include "foc_current_median.h"
/* Frozen 2026-10-14 implementation. Do not refactor this test oracle together
 * with production: comparisons include every estimator update, not just FU/FV. */
FOC_HOT_INLINE uint16_t RefAdaptive_Jump(const FocAdaptiveNoise *s)
{
    uint32_t t=(6U*s->noise_q8+128U)/256U;
    return (uint16_t)(t<20U?20U:t>40U?40U:t);
}
FOC_HOT_INLINE uint8_t RefAdaptive_Isolated(const FocAdaptiveNoise *s,
    uint16_t p,uint16_t a,uint16_t b,uint16_t c)
{
    if (p>4095U || a>4095U || b>4095U || c>4095U ||
        !((b>a && b>c)||(b<a && b<c))) return 0U;
    uint32_t ab=FocTrend4_Distance(a,b),bc=FocTrend4_Distance(b,c);
    if (ab<=20U || bc<=20U) return 0U;
    uint32_t ac=FocTrend4_Distance(a,c);
    uint16_t jump=40U;
    if (!(ac<=30U && ab>40U && bc>40U)) {
        if (FocTrend4_Distance(p,a)>10U || ac>10U) return 0U;
        jump=RefAdaptive_Jump(s);
        if (ab<=jump || bc<=jump) return 0U;
    }
    int32_t prediction3=3*(int32_t)a+c-p;
    int32_t residual3=3*(int32_t)b-prediction3;
    return prediction3>=0 && prediction3<=3*4095 &&
        (residual3>3*(int32_t)jump || residual3< -3*(int32_t)jump);
}
FOC_HOT_INLINE void RefAdaptive_Learn(FocAdaptiveNoise *s,
    uint16_t p,uint16_t a,uint16_t b,uint16_t c,uint8_t repaired)
{
    if (repaired || p>4095U || a>4095U || b>4095U || c>4095U ||
        FocTrend4_Distance(p,a)>10U || FocTrend4_Distance(a,b)>10U ||
        FocTrend4_Distance(b,c)>10U) { s->quiet=0U; return; }
    int32_t r=3*(int32_t)b-(3*(int32_t)a+c-p);
    uint32_t residual=(uint32_t)(r<0?-r:r);
    if (residual>30U) { s->quiet=0U; return; }
    if (s->quiet<16U) { ++s->quiet; return; }
    uint32_t target=(residual*256U+1U)/3U;
    if (target<256U) target=256U;
    if (target>2048U) target=2048U;
    s->noise_q8=(uint16_t)((int32_t)s->noise_q8+
        ((int32_t)target-s->noise_q8)/64);
    if (s->learned!=UINT32_MAX) ++s->learned;
}
FOC_HOT_INLINE int RefAdaptive_Push(FocCurrentMedian *m,uint16_t u,uint16_t v,
    uint16_t *filtered_u,uint16_t *filtered_v)
{
    m->u[m->index]=u; m->v[m->index]=v;
    m->index=(uint8_t)((m->index+1U)%4U);
    if (m->count<4U) ++m->count;
    m->last_spike_mask=0U;
    if (m->count<4U) return 0;
    uint8_t p=m->index,a=(uint8_t)((p+1U)%4U);
    uint8_t b=(uint8_t)((p+2U)%4U),c=(uint8_t)((p+3U)%4U);
    m->last_spike_mask=RefAdaptive_Isolated(&m->noise[0],m->u[p],m->u[a],m->u[b],m->u[c]) |
        (uint8_t)(RefAdaptive_Isolated(&m->noise[1],m->v[p],m->v[a],m->v[b],m->v[c])<<1U);
    RefAdaptive_Learn(&m->noise[0],m->u[p],m->u[a],m->u[b],m->u[c],m->last_spike_mask);
    RefAdaptive_Learn(&m->noise[1],m->v[p],m->v[a],m->v[b],m->v[c],m->last_spike_mask);
    *filtered_u=(m->last_spike_mask&1U)?(uint16_t)(((uint32_t)m->u[a]+m->u[c]+1U)/2U):m->u[b];
    *filtered_v=(m->last_spike_mask&2U)?(uint16_t)(((uint32_t)m->v[a]+m->v[c]+1U)/2U):m->v[b];
    return 1;
}
#endif
