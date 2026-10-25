#ifndef FOC_CURRENT_ADAPTIVE_H
#define FOC_CURRENT_ADAPTIVE_H
#include "foc_current_trend4.h"
/* Experimental, bounded noise learning. No heap, sort, lookahead beyond the
 * existing next physical sample, or learning from repaired feedback. The
 * original 30/40 detector remains intact; only SMALLER isolated candidates
 * gain a quiet-history admission. A real one-period pulse is still ambiguous. */
typedef struct {
    uint16_t noise_q8;
    uint8_t quiet;
    uint32_t learned;
} FocAdaptiveNoise;
static inline void FocAdaptive_Begin(FocAdaptiveNoise *s)
{ *s=(FocAdaptiveNoise){.noise_q8=1707U}; } /* Start at the existing 40-count bound. */
FOC_HOT_INLINE uint16_t FocAdaptive_Jump(const FocAdaptiveNoise *s)
{
    uint32_t t=(6U*s->noise_q8+128U)/256U;
    return (uint16_t)(t<20U?20U:t>40U?40U:t);
}
typedef struct {
    uint8_t isolated;
    /* 0 is ineligible; 1..31 encode a quiet residual of 0..30 counts.
     * A quiet window and an isolated candidate are mutually exclusive. */
    uint8_t quiet_residual_plus1;
} FocAdaptiveWindow;

FOC_HOT_INLINE FocAdaptiveWindow FocAdaptive_Analyze(const FocAdaptiveNoise *s,
    uint16_t p,uint16_t a,uint16_t b,uint16_t c)
{
    FocAdaptiveWindow result={0U,0U};
    if (p>4095U || a>4095U || b>4095U || c>4095U) return result;
    uint32_t ab=FocTrend4_Distance(a,b),bc=FocTrend4_Distance(b,c);
    /* Reuse validity/differences for learning. Such a window cannot satisfy
     * the detector's ab>20 && bc>20, so no detector work is needed here. */
    if (ab<=10U && bc<=10U) {
        if (FocTrend4_Distance(p,a)>10U) return result;
        int32_t r=3*(int32_t)b-(3*(int32_t)a+c-p);
        uint32_t residual=(uint32_t)(r<0?-r:r);
        if (residual<=30U) result.quiet_residual_plus1=(uint8_t)(residual+1U);
        return result;
    }
    if (ab<=20U || bc<=20U || !((b>a && b>c)||(b<a && b<c))) return result;
    uint32_t ac=FocTrend4_Distance(a,c);
    uint16_t jump=40U;
    if (!(ac<=30U && ab>40U && bc>40U)) {
        if (FocTrend4_Distance(p,a)>10U || ac>10U) return result;
        jump=FocAdaptive_Jump(s);
        if (ab<=jump || bc<=jump) return result;
    }
    int32_t prediction3=3*(int32_t)a+c-p;
    int32_t residual3=3*(int32_t)b-prediction3;
    result.isolated=prediction3>=0 && prediction3<=3*4095 &&
        (residual3>3*(int32_t)jump || residual3< -3*(int32_t)jump);
    return result;
}
FOC_HOT_INLINE void FocAdaptive_LearnWindow(FocAdaptiveNoise *s,
    FocAdaptiveWindow window,uint8_t repaired)
{
    if (repaired || !window.quiet_residual_plus1) { s->quiet=0U; return; }
    if (s->quiet<16U) { ++s->quiet; return; }
    uint32_t residual=(uint32_t)window.quiet_residual_plus1-1U;
    uint32_t target=(residual*256U+1U)/3U;
    if (target<256U) target=256U;
    if (target>2048U) target=2048U;
    /* 1/64 EWMA, integer division truncates toward zero symmetrically. */
    s->noise_q8=(uint16_t)((int32_t)s->noise_q8+
        ((int32_t)target-s->noise_q8)/64);
    if (s->learned!=UINT32_MAX) ++s->learned;
}
/* Keep the standalone helpers for callers/tests. The paired hot path below
 * analyzes each physical channel only once, then applies the shared mask. */
FOC_HOT_INLINE uint8_t FocAdaptive_Isolated(const FocAdaptiveNoise *s,
    uint16_t p,uint16_t a,uint16_t b,uint16_t c)
{ return FocAdaptive_Analyze(s,p,a,b,c).isolated; }
FOC_HOT_INLINE void FocAdaptive_Learn(FocAdaptiveNoise *s,
    uint16_t p,uint16_t a,uint16_t b,uint16_t c,uint8_t repaired)
{ FocAdaptive_LearnWindow(s,FocAdaptive_Analyze(s,p,a,b,c),repaired); }
#endif
