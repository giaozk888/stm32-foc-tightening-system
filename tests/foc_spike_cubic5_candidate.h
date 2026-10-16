#ifndef FOC_SPIKE_CUBIC5_CANDIDATE_H
#define FOC_SPIKE_CUBIC5_CANDIDATE_H
#include <stdint.h>
/* OFFLINE CANDIDATE ONLY: not included by any firmware target.
 * p,a,b,c,d are five consecutive physical samples; b is two periods old.
 * OFFLINE_QUADRATIC4 uses only p,a,b,c and waits one period, not two.
 * Trend uses cubic interpolation of p,a,c,d, with b excluded.
 * Classification is NOT proof that a physical pulse is interference. */
static inline uint32_t Cubic5_Distance(uint16_t a,uint16_t b)
{ return a>b?(uint32_t)a-b:(uint32_t)b-a; }
static inline uint8_t Cubic5_Isolated(const uint16_t x[5])
{
    uint16_t p=x[0],a=x[1],b=x[2],c=x[3],d=x[4];
#if defined(OFFLINE_QUADRATIC4)
    for (unsigned i=0;i<4U;++i) if (x[i]>4095U) return 0U;
#else
    for (unsigned i=0;i<5U;++i) if (x[i]>4095U) return 0U;
#endif
    if (!((b>a && b>c)||(b<a && b<c)) || Cubic5_Distance(a,c)>30U ||
        Cubic5_Distance(a,b)<=40U || Cubic5_Distance(b,c)<=40U) return 0U;
#if defined(OFFLINE_QUADRATIC4)
    (void)d;
    int32_t prediction6=2*(3*(int32_t)a+c-p);
#else
    int32_t prediction6=4*(int32_t)a+4*(int32_t)c-p-d;
#endif
    int32_t residual6=6*(int32_t)b-prediction6;
    if (prediction6<0 || prediction6>6*4095) return 0U;
    return residual6>240 || residual6< -240;
}
static inline uint16_t Cubic5_Select(const uint16_t x[5])
{ return Cubic5_Isolated(x)?(uint16_t)(((uint32_t)x[1]+x[3]+1U)/2U):x[2]; }
#endif
