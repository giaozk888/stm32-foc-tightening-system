#include <assert.h>
#include <stdio.h>
#include "foc_zero_median.h"
static FocZeroMedian m;
static FocZeroCal c;
static void settle(void) {
    FocZeroMedian_Begin(&m, &c, 1561);
    for (unsigned i=0; i<FOC_ZERO_SETTLE_PAIRS; ++i)
        FocZeroMedian_Push(&m, &c, 1561, 1561);
}
int main(void) {
    settle();
    for (unsigned i=0;i<FOC_ZERO_WINDOW_PAIRS;++i)
        FocZeroMedian_Push(&m,&c,i==90?1668:1561,i==90?1671:1561);
    assert(c.state==FOC_ZERO_READY && c.zero_u==1561 && c.zero_v==1561);
    assert(m.raw.state==FOC_ZERO_FAILED && m.raw.reason==FOC_ZERO_OUT_OF_RANGE);
    assert(m.outside_nominal==1 && m.changed==1 && m.pairs==24000);
    assert(m.raw.last_u==1668 && m.raw.last_v==1671);
    settle();
    FocZeroMedian_Push(&m,&c,1668,1671);
    FocZeroMedian_Push(&m,&c,1668,1671);
    assert(c.state==FOC_ZERO_FAILED); /* Sustained fault cannot be filtered away. */
    settle();
    FocZeroMedian_Push(&m,&c,5000,1561);
    assert(c.state==FOC_ZERO_FAILED && c.zero_u==0 && c.zero_v==0);
    settle();
    for (unsigned i=0;i<4000;++i) FocZeroMedian_Push(&m,&c,1561,1561);
    assert(m.raw.state==FOC_ZERO_READY && c.state==FOC_ZERO_READY && m.changed==0);
    unsigned old=m.pairs;
    FocZeroMedian_Push(&m,&c,1668,1671);
    assert(m.pairs==old); /* Terminal is latched. */
    FocZeroMedian_Begin(&m,&c,0);
    assert(c.state==FOC_ZERO_FAILED && m.raw.state==FOC_ZERO_FAILED);
    puts("Median diagnostic host checks PASS");
}
