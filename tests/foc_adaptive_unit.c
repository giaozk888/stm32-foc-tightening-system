#include <assert.h>
#include <stdio.h>
#include "foc_current_adaptive.h"
#include "foc_zero_robust.h"
int main(void)
{
    FocAdaptiveNoise s; FocAdaptive_Begin(&s);
    assert(FocAdaptive_Jump(&s)==40U);
    for (unsigned n=0U;n<100000U;++n) {
        FocAdaptive_Learn(&s,1560U,1561U,1560U,1561U,0U);
        assert(FocAdaptive_Jump(&s)>=20U && FocAdaptive_Jump(&s)<=40U);
    }
    uint16_t before=s.noise_q8;
    FocAdaptive_Learn(&s,1560U,1560U,2400U,1560U,1U);
    assert(s.noise_q8==before && !s.quiet);
    FocAdaptive_Learn(&s,1560U,1560U,65535U,1560U,0U);
    assert(s.noise_q8==before);
    s.noise_q8=2048U; assert(FocAdaptive_Jump(&s)==40U);
    /* Actual reset must initialize the estimator, never divide by a mutable
     * scale or depend on heap/FP. Sudden changes cannot train noise upward. */
    for (unsigned n=0U;n<1000U;++n) FocAdaptive_Learn(&s,1200U,1600U,2000U,2400U,0U);
    assert(s.noise_q8==2048U);
    FocAdaptive_Begin(&s);
    for (unsigned n=0U;n<100U;++n) FocAdaptive_Learn(&s,1560U,1560U,1560U,1560U,0U);
    assert(FocAdaptive_Isolated(&s,1560U,1560U,1585U,1560U));
    assert(!FocAdaptive_Isolated(&s,1560U,1560U,1580U,1560U));
    assert(!FocAdaptive_Isolated(&s,1560U,1560U,1900U,1900U));
    assert(!FocAdaptive_Isolated(&s,1560U,1560U,65535U,1560U));
    /* Exhaust all 5! permutations to verify the median network indirectly. */
    for (unsigned a=0;a<5U;++a) for (unsigned b=0;b<5U;++b)
    for (unsigned c=0;c<5U;++c) for (unsigned d=0;d<5U;++d)
    for (unsigned e=0;e<5U;++e) {
        if (a==b || a==c || a==d || a==e || b==c || b==d || b==e || c==d || c==e || d==e) continue;
        FocZeroRobust r; FocZeroCal z; FocZeroRobust_Begin(&r); FocZero_Begin(&z,1560U);
        z.state=FOC_ZERO_COLLECTING;
        unsigned order[5]={a,b,c,d,e};
        for (unsigned n=0U;n<5U;++n) FocZeroRobust_Push(&r,&z,(uint16_t)(1558U+order[n]),1560U);
        assert(z.count==5U && z.sum_u==5U*1560U && z.sum_v==5U*1560U);
    }
    puts("PASS adaptive threshold bounds, frozen learning, median5 120 permutations"); return 0;
}
