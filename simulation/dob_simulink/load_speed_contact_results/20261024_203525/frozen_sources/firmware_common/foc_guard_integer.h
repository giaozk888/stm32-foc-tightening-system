#ifndef FOC_GUARD_INTEGER_H
#define FOC_GUARD_INTEGER_H
#include <float.h>
#include <stdint.h>
#include <string.h>
#include "foc_hot_path.h"
#if !defined(FOC_GUARD_FAST_PATH) || !defined(FOC_PAIR_FAST_PATH)
#error Integer guard requires the separate protected pair-fast candidate
#endif
_Static_assert(sizeof(float)==sizeof(uint32_t) && FLT_RADIX==2 &&
               FLT_MANT_DIG==24 && FLT_MAX_EXP==128 && FLT_MIN_EXP==-125,
               "Integer guard requires IEEE binary32");
/* Pointer input is intentional: hard-float value arguments can generate a
 * VFP load/move even for a bit test. Character accesses are alias-safe and
 * preserve volatile reads; the linked guardian is checked for VFP instructions.
 * Callers serialize shared float publication just as for the old checks. */
static inline uint32_t FocGuard_Bits(const volatile float *value)
{
    uint32_t bits;
    const volatile unsigned char *source=(const volatile unsigned char *)value;
    unsigned char *target=(unsigned char *)&bits;
    target[0]=source[0]; target[1]=source[1];
    target[2]=source[2]; target[3]=source[3];
    return bits;
}
static inline uint8_t FocGuard_Finite(const volatile float *value)
{
    return (FocGuard_Bits(value)&UINT32_C(0x7fffffff))<UINT32_C(0x7f800000);
}
static inline uint8_t FocGuard_Within(const volatile float *value,const float *limit)
{
    uint32_t bound;
    memcpy(&bound,limit,sizeof bound);
    /* Reject negative/nonfinite limits; +0 is a valid magnitude bound. */
    return bound<UINT32_C(0x7f800000) &&
        (FocGuard_Bits(value)&UINT32_C(0x7fffffff))<=bound;
}
#endif
