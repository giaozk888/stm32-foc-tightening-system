/* Same shared diagnostic core as the board, stdin only, no peripherals. */
#include "switch_feedback_core.h"
#include <stdio.h>
int main(void)
{
    SwitchFeedbackStats s;
    SwitchFeedback_Begin(&s,SWITCH_PWM,1560,1560,595);
    unsigned u,v;
    while (scanf("%u %u",&u,&v)==2) {
        if (u>4095 || v>4095 || s.count>=SWITCH_FEEDBACK_PAIRS) return 2;
        unsigned reason=SwitchFeedback_Push(&s,(uint16_t)u,(uint16_t)v);
        if (reason && reason!=SWITCH_DONE) return 3;
    }
    if (!feof(stdin) || s.count<4) return 4;
    printf("{\"N\":%lu,\"SUM\":[%lu,%lu],\"RANGE\":[[%u,%u],[%u,%u]],\"REPAIR\":[%lu,%lu]}\n",
        (unsigned long)s.trend_count,(unsigned long)s.trend_sum_u,(unsigned long)s.trend_sum_v,
        s.trend_min_u,s.trend_max_u,s.trend_min_v,s.trend_max_v,
        (unsigned long)s.trend_repairs_u,(unsigned long)s.trend_repairs_v);
    return 0;
}
