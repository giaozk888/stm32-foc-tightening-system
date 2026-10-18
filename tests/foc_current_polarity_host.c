/* Synthetic numeric/protection checks only; no board or actuator access. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "foc_feedback_safety_candidate.h"
#define assert(x) do { if (!(x)) { \
    fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while (0)

static FocFeedbackSafety s;
static void begin(void)
{
    FocFeedbackSafetyConfig cfg={.protection={4.0f,100U,100U,6U,4U},
        .zero_u=1563U,.zero_v=1561U,.count_to_A=3300.0f/(4095.0f*120.0f)};
    assert(FocFeedbackSafety_Begin(&s,cfg,0U)==FOC_OC_CLEAR);
    assert(s.raw_trip_counts==595U);
}
static FocOcConfirmResult push(unsigned seq,unsigned u,unsigned v)
{
    return FocFeedbackSafety_Push(&s,seq,50U*seq,(uint16_t)u,(uint16_t)v,
        1.31323111f,0U,1U);
}
int main(void)
{
    float scale=3300.0f/(4095.0f*120.0f);
    assert(FocCurrentFeedback_FromRaw(1563,1563,scale)==0.0f);
    assert(FocCurrentFeedback_FromRaw(0,4095,scale)==
           -FocCurrentFeedback_FromRaw(4095,0,scale));
    begin();
    assert(push(1,1553,1581)==FOC_OC_CLEAR);
    FocFeedbackFrame frame;
    assert(FocFeedbackSafety_Take(&s,50U,0U,1U,&frame));
    assert(fabsf(frame.iu_A-FOC_CURRENT_FEEDBACK_SIGN*(-10.0f)*scale)<1e-6f);
    assert(fabsf(frame.iv_A-FOC_CURRENT_FEEDBACK_SIGN*20.0f*scale)<1e-6f);
    assert(frame.iw_A==-(frame.iu_A+frame.iv_A));
    assert(frame.source_seq==1U && frame.u==1553 && frame.v==1581);
    /* The actual last-fault pair: only sign changes, not scaling or channels. */
    float iu=FocCurrentFeedback_FromRaw(1271,1563,scale);
    float iv=FocCurrentFeedback_FromRaw(1873,1561,scale);
    assert(fabsf(fabsf(iu)-1.96092796f)<1e-5f);
    assert(fabsf(fabsf(iv)-2.09523810f)<1e-5f);
    /* A suspect sample is still held; no invented feedback or fake PI frame. */
    assert(push(2,1740,1581)==FOC_OC_CLEAR);
    assert(!FocFeedbackSafety_Take(&s,100U,0U,1U,&frame));
    assert(push(3,1553,1581)==FOC_OC_CLEAR);
    assert(s.validation.current_confirmed_spike==1U);
    /* Unresolved limit and fault remain unchanged. */
    begin();
    assert(push(1,1750,1750)!=FOC_OC_TRIPPED);
    assert(push(2,1410,1410)!=FOC_OC_TRIPPED);
    assert(push(3,1800,1800)!=FOC_OC_TRIPPED);
    assert(push(4,1300,1300)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_CURRENT_INVALID);
    assert(s.validation.current_unresolved_consecutive==3U);
    /* Raw protection is deliberately independent of CONTROL sign. */
    begin();
    assert(push(1,900,1561)!=FOC_OC_TRIPPED);
    assert(s.protection.pending && s.protection.pending_mask==5U); /* U and W */
    assert(push(2,900,1561)!=FOC_OC_TRIPPED);
    assert(push(3,900,1561)!=FOC_OC_TRIPPED);
    assert(push(4,900,1561)!=FOC_OC_TRIPPED);
    assert(push(5,900,1561)==FOC_OC_TRIPPED);
    assert(s.protection.cur_confirm_fault_count==1U);
    begin();
    assert(push(1,1200,1200)!=FOC_OC_TRIPPED);
    assert(s.protection.pending_mask & 4U); /* reconstructed W */
    puts("PASS current polarity: feedback sign only, protection unchanged");
}
