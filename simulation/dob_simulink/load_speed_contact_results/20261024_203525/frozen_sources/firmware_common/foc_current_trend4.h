#ifndef FOC_CURRENT_TREND4_H
#define FOC_CURRENT_TREND4_H
#include <stdint.h>
#include "foc_hot_path.h"
/* Four consecutive physical samples p,a,b,c; b is one period old.
 * Integer quadratic prediction excludes b. Classification alone cannot
 * distinguish interference from a real one-period current pulse. */
FOC_HOT_INLINE uint32_t FocTrend4_Distance(uint16_t a, uint16_t b)
{ return a > b ? (uint32_t)a-b : (uint32_t)b-a; }
FOC_HOT_INLINE uint8_t FocTrend4_Isolated(uint16_t p, uint16_t a,
                                       uint16_t b, uint16_t c)
{
    if (p > 4095U || a > 4095U || b > 4095U || c > 4095U) return 0U;
    if (!((b>a && b>c) || (b<a && b<c)) ||
        FocTrend4_Distance(a,c)>30U || FocTrend4_Distance(a,b)<=40U ||
        FocTrend4_Distance(b,c)<=40U) return 0U;
    int32_t prediction3=3*(int32_t)a+c-p;
    int32_t residual3=3*(int32_t)b-prediction3;
    if (prediction3<0 || prediction3>3*4095) return 0U;
    return residual3>120 || residual3< -120;
}
static inline uint16_t FocTrend4_Select(uint16_t p, uint16_t a,
                                      uint16_t b, uint16_t c)
{
    return FocTrend4_Isolated(p,a,b,c) ?
        (uint16_t)(((uint32_t)a+c+1U)/2U) : b;
}
/* Keep the encoder's predicted angle from the same physical callback as b.
 * Measurement Park uses center; voltage inverse Park uses the current angle.
 * This aligns the software estimates, not the encoder's hardware timestamp. */
typedef struct { float previous, center; } FocTrend4Angle;
static inline void FocTrend4Angle_Push(FocTrend4Angle *h, float now)
{ h->center=h->previous; h->previous=now; }
static inline int FocTrend4_RawTrip(uint16_t u, uint16_t v,
                                   uint16_t zu, uint16_t zv,
                                   float count_to_A, float limit_A)
{
    if (u>4095U || v>4095U || !(count_to_A>0.0f) || !(limit_A>0.0f)) return 1;
    float iu=((int32_t)zu-(int32_t)u)*count_to_A;
    float iv=((int32_t)zv-(int32_t)v)*count_to_A;
    float iw=-(iu+iv);
    return iu>limit_A || iu< -limit_A || iv>limit_A || iv< -limit_A ||
           iw>limit_A || iw< -limit_A;
}
#endif
