/* Offline stdin/stdout replay of the actual shared C filter. No peripherals. */
#include <stdint.h>
#include <stdio.h>
#include "foc_current_median.h"
int main(void)
{
    FocCurrentMedian m; unsigned u, v, n = 0;
    uint16_t fu, fv;
    FocCurrentMedian_Begin(&m);
    while (scanf("%u %u", &u, &v) == 2) {
        if (u > 4095U || v > 4095U) return 2;
        ++n;
        if (FocCurrentMedian_Push(&m,(uint16_t)u,(uint16_t)v,&fu,&fv))
            printf("%u %u %u %u\n",n-2,fu,fv,m.last_spike_mask);
    }
    return 0;
}
