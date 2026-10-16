/* stdin-only replay of production selectors/zero binding. No board access. */
#include <stdio.h>
#include <string.h>
#include <time.h>
#include "foc_current_median.h"
#include "foc_zero_median.h"
#if defined(FOC_ADAPTIVE_REFERENCE)
#include "foc_adaptive_reference.h"
#define FocCurrentMedian_Push RefAdaptive_Push
#endif
int main(int argc,char **argv)
{
    if (argc==2 && !strcmp(argv[1],"--bench")) {
        FocCurrentMedian m; FocCurrentMedian_Begin(&m);
        uint16_t u=0U,v=0U; volatile uint32_t digest=0U;
        clock_t start=clock();
        for (unsigned i=0U;i<20000000U;++i) {
            uint16_t x=(uint16_t)(1560U+i%5U+(i%101U==50U?28U:0U));
            if (FocCurrentMedian_Push(&m,x,1560U,&u,&v)) digest+=u+v;
        }
        printf("{\"host_ns_per_pair\":%.3f,\"digest\":%lu}\n",
            1.e9*(double)(clock()-start)/CLOCKS_PER_SEC/20000000.0,(unsigned long)digest);
        return 0;
    }
    if (argc==2 && (!strcmp(argv[1],"--zero") || !strcmp(argv[1],"--zero-window"))) {
        FocZeroMedian m; FocZeroCal c;
        FocZeroMedian_Begin(&m,&c,1560U);
        if (!strcmp(argv[1],"--zero-window")) {
            c.state=m.raw.state=FOC_ZERO_COLLECTING;
            c.settled=m.raw.settled=FOC_ZERO_SETTLE_PAIRS;
        }
        unsigned u,v,n=0U;
        while (scanf("%u %u",&u,&v)==2) {
            if (u>65535U || v>65535U) return 2;
            FocZeroMedian_Push(&m,&c,(uint16_t)u,(uint16_t)v); ++n;
        }
        if (!feof(stdin)) return 3;
        printf("{\"input_pairs\":%u,\"state\":%u,\"reason\":%u,\"zero\":[%u,%u],"
            "\"count\":%lu,\"total_used\":%lu,\"raw_state\":%u,\"raw_reason\":%u,\"changed\":%lu",
            n,c.state,c.reason,c.zero_u,c.zero_v,(unsigned long)c.count,
            (unsigned long)c.total,m.raw.state,m.raw.reason,(unsigned long)m.changed);
#if defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM)
        printf(",\"segments\":%u,\"outliers\":%lu,\"robust_flags\":%u",
            m.robust.segments,(unsigned long)m.robust.outliers,m.robust.flags);
#endif
        puts("}"); return 0;
    }
    FocCurrentMedian m; FocCurrentMedian_Begin(&m);
    unsigned u,v,n=0U;
    while (scanf("%u %u",&u,&v)==2) {
        if (u>65535U || v>65535U) return 2;
        uint16_t fu=0U,fv=0U;
        if (FocCurrentMedian_Push(&m,(uint16_t)u,(uint16_t)v,&fu,&fv)) {
            printf("%u %u %u %u",n-1U,fu,fv,m.last_spike_mask);
#if defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM)
            if (argc==2 && !strcmp(argv[1],"--state"))
                printf(" %u %u %lu %u %u %lu",m.noise[0].noise_q8,m.noise[0].quiet,
                    (unsigned long)m.noise[0].learned,m.noise[1].noise_q8,m.noise[1].quiet,
                    (unsigned long)m.noise[1].learned);
#endif
            puts("");
        }
        ++n;
    }
    return feof(stdin)?0:3;
}
