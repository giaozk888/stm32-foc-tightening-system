#include "foc_zero_median.h"
#include <stdint.h>

static FocZeroMedian median;
static FocZeroCal cal;
void zero_begin(void)
{
    FocZeroMedian_Begin(&median,&cal,1561U);
    for (unsigned i=0;i<FOC_ZERO_SETTLE_PAIRS;++i)
        FocZeroMedian_Push(&median,&cal,1561U,1561U);
}
void zero_push(uint16_t u,uint16_t v)
{ FocZeroMedian_Push(&median,&cal,u,v); }
void zero_read(uint32_t *out)
{
    out[0]=cal.state; out[1]=cal.count; out[2]=median.robust.reject_count;
    out[3]=median.robust.total_count; out[4]=median.robust.max_consecutive_reject;
    out[5]=cal.zero_u; out[6]=cal.zero_v; out[7]=cal.sum_u; out[8]=cal.sum_v;
    out[9]=median.robust.flags; out[10]=cal.reason; out[11]=median.robust.segments;
}
