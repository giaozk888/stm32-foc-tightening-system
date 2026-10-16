#include <assert.h>
#include <stdio.h>
#include "foc_feedback_safety_candidate.h"
static void begin(FocFeedbackSafety *s)
{
    assert(FocFeedbackSafety_Begin(s,(FocFeedbackSafetyConfig){
        .protection={4.0f,100U,100U,6U,4U},.zero_u=1560U,.zero_v=1560U,.count_to_A=.01f},0U)==FOC_OC_CLEAR);
}
int main(void)
{
    FocFeedbackSafety s; FocFeedbackFrame frame; begin(&s);
    unsigned seq=0U;
    for (;seq<150U;++seq) {
        assert(FocFeedbackSafety_Push(&s,seq,seq*50U,1560U,1560U,(float)seq,0U,1U)!=FOC_OC_TRIPPED);
        int ready=FocFeedbackSafety_Take(&s,seq*50U,0U,1U,&frame);
        if (seq>=3U) {
            assert(ready && frame.source_seq==seq-1U && frame.source_us==(seq-1U)*50U);
            assert(frame.measurement_angle==(float)(seq-1U) && frame.actuation_angle==(float)seq);
        } else assert(!ready);
    }
    for (;seq<180U && s.protection.result!=FOC_OC_TRIPPED;++seq)
        (void)FocFeedbackSafety_Push(&s,seq,seq*50U,2100U,1560U,(float)seq,0U,1U);
    assert(s.protection.result==FOC_OC_TRIPPED && s.protection.reason==FOC_FP_CONFIRMED_CURRENT);
    begin(&s);
    assert(FocFeedbackSafety_Push(&s,0U,0U,5000U,1560U,0.0f,0U,1U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_RAW_INVALID);
    begin(&s);
    assert(FocFeedbackSafety_Push(&s,0U,0U,1560U,1560U,0.0f,0U,1U)!=FOC_OC_TRIPPED);
    assert(FocFeedbackSafety_Poll(&s,101U,0U,1U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_TIMEOUT);
    begin(&s);
    for (seq=0U;seq<180U && s.protection.result!=FOC_OC_TRIPPED;++seq) {
        uint16_t u=(seq>=150U && (seq-150U)%4U==0U)?1585U:1560U;
        (void)FocFeedbackSafety_Push(&s,seq,seq*50U,u,1560U,(float)seq,0U,1U);
    }
    assert(s.protection.result==FOC_OC_TRIPPED && s.protection.reason==FOC_FP_REPAIR_BUDGET);
    puts("PASS adaptive actual feedback: physical timestamp/angle, 4A 2-of-3, invalid raw, timeout, 6/32 repair budget");
    return 0;
}
