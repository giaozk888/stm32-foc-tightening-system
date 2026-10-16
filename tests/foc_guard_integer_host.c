#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "foc_guard_integer.h"
static void check(uint32_t bits)
{
    float value;
    memcpy(&value,&bits,sizeof value);
    const float limit=60.0f;
    assert(FocGuard_Bits(&value)==bits);
    assert(FocGuard_Finite(&value)==!!isfinite(value));
    assert(FocGuard_Within(&value,&limit)==(isfinite(value) && fabsf(value)<=limit));
}
int main(void)
{
    uint32_t bits=UINT32_C(0x19a652dd);
    for(unsigned i=0;i<1000000U;++i) {
        bits^=bits<<13U; bits^=bits>>17U; bits^=bits<<5U; check(bits);
    }
    const uint32_t edge[]={0U,0x80000000U,1U,0x80000001U,0x007fffffU,
        0x00800000U,0x7f7fffffU,0xff7fffffU,0x7f800000U,0xff800000U,
        0x7fc00000U,0xffc00000U,0x7f800001U,0x42700000U,0x42700001U,
        0xc2700000U,0xc2700001U};
    for(unsigned i=0;i<sizeof edge/sizeof edge[0];++i) check(edge[i]);
    float zero=0.0f;
    const float invalid_limits[]={-60.0f,-0.0f,INFINITY,NAN};
    for(unsigned i=0;i<sizeof invalid_limits/sizeof invalid_limits[0];++i)
        assert(!FocGuard_Within(&zero,&invalid_limits[i]));
    puts("PASS 1000000 binary32 patterns and finite/60-rpm edge cases");
}
