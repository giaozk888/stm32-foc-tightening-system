#include <stdio.h>
#include "bridge_feedback_filter_core.h"
int main(void)
{
    unsigned zu,zv,mv,n,u,v,us;
    if (scanf("%u %u %u %u",&zu,&zv,&mv,&n)!=4 || zu>4095 || zv>4095 || n>1000) return 2;
    BridgeFeedbackFilter s;
    if (!BridgeFilter_Begin(&s,(uint16_t)zu,(uint16_t)zv,mv)) return 3;
    for (unsigned i=0;i<n;i++) {
        if (scanf("%u %u %u",&u,&v,&us)!=3 || u>65535 || v>65535) return 4;
        BridgeFilter_Push(&s,(uint16_t)u,(uint16_t)v,us);
    }
    printf("N=%lu FN=%lu REPAIRED=%lu RESULT=%u REASON=%u LAST_US=%lu\n",
        (unsigned long)s.protection.raw_pairs,(unsigned long)s.protection.feedback_pairs,
        (unsigned long)s.protection.repaired_pairs,s.protection.result,s.protection.reason,
        (unsigned long)s.protection.last_us);
    return 0;
}
