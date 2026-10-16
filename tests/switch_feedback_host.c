#include "switch_feedback_core.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    SwitchFeedbackStats s;
    SwitchFeedback_Begin(&s, SWITCH_OFF, 1561, 1561, 595);
    for (unsigned i=0;i<SWITCH_FEEDBACK_PAIRS;i++)
        assert(SwitchFeedback_Push(&s,1561,1561)==(i+1==SWITCH_FEEDBACK_PAIRS?SWITCH_DONE:0));
    assert(s.count==3600 && s.filtered_count==3598 && !s.outside && !s.first_bad_pair);
    assert(s.sum_u==1561*3600U && s.filtered_sum_v==1561*3598U);
    assert(s.trend_count==3597 && s.trend_sum_u==1561*3597U && !s.trend_repairs_u);
    assert(s.trend_min_v==1561 && s.trend_max_v==1561);
    assert(SwitchFeedback_Push(&s,1561,1561)==SWITCH_CONFIG);
    SwitchFeedback_Begin(&s, SWITCH_PWM, 1561,1561,595);
    assert(!SwitchFeedback_Push(&s,1561,1561));
    assert(!SwitchFeedback_Push(&s,2200,1561)); /* Still SD=0, retain raw defect. */
    assert(!SwitchFeedback_Push(&s,1561,1561));
    assert(s.first_bad_pair==2 && s.first_bad_u==2200 && s.outside==1);
    assert(s.filtered_count==1 && s.fmax_u==1561 && s.max_u==2200);
    SwitchFeedback_Begin(&s,SWITCH_BRIDGE,1561,1561,595);
    assert(SwitchFeedback_Push(&s,2200,1561)==SWITCH_RAW_CURRENT); /* First pair, no warm bypass. */
    SwitchFeedback_Begin(&s,SWITCH_BRIDGE,1561,1561,595);
    assert(SwitchFeedback_Push(&s,1861,1861)==SWITCH_RAW_CURRENT); /* W=-600 trips independently. */
    SwitchFeedback_Begin(&s,SWITCH_BRIDGE,1561,1561,595);
    assert(!SwitchFeedback_Push(&s,1561,1561));
    for (unsigned i=0;i<20;i++)
        assert(SwitchFeedback_Push(&s,(i&1)?1561:1631,1561)==(i==19?SWITCH_STALE:0));
    assert(s.max_reject_streak==20);
    SwitchFeedback_Begin(&s,SWITCH_BRIDGE,1561,1561,0);
    assert(SwitchFeedback_Push(&s,1561,1561)==SWITCH_RAW_CURRENT);
    SwitchFeedback_Begin(&s,SWITCH_PWM,1561,1561,595);
    assert(!SwitchFeedback_Push(&s,1561,1561));
    assert(!SwitchFeedback_Push(&s,1561,1561));
    assert(!SwitchFeedback_Push(&s,2200,1561));
    assert(!SwitchFeedback_Push(&s,1561,1561));
    assert(s.first_bad_pair==3 && s.trend_count==1 && s.trend_repairs_u==1);
    assert(s.trend_sum_u==1561 && s.trend_sum_v==1561);
    /* Observer cannot turn a repaired raw overcurrent into permission. */
    SwitchFeedback_Begin(&s,SWITCH_BRIDGE,1561,1561,595);
    assert(!SwitchFeedback_Push(&s,1561,1561));
    assert(!SwitchFeedback_Push(&s,1561,1561));
    assert(SwitchFeedback_Push(&s,2200,1561)==SWITCH_RAW_CURRENT);
    puts("SWITCH CORE PASS: finite count, raw-before-median, raw U/V/W trip, stale gate");
}
