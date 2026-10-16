#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include "foc_feedback_safety_candidate.h"

static FocFeedbackSafety fixture(void)
{
    FocFeedbackSafety s;
    FocFeedbackSafetyConfig cfg = {
        .protection = {4.0f, 100U, 100U, 3U, 2U},
        .zero_u = 1600U, .zero_v = 1600U, .count_to_A = 0.01f
    };
    assert(FocFeedbackSafety_Begin(&s, cfg, 0U) == FOC_OC_CLEAR);
    return s;
}
static FocOcConfirmResult push(FocFeedbackSafety *s, uint32_t n, uint16_t u, uint16_t v)
{ return FocFeedbackSafety_Push(s, n, n*50U, u, v, (float)n, 0U, 1U); }
static int take(FocFeedbackSafety *s, FocFeedbackFrame *f)
{ return FocFeedbackSafety_Take(s,s->protection.last_us,0U,1U,f); }
static void warm(FocFeedbackSafety *s)
{ for (uint32_t n=1U; n<=4U; ++n) assert(push(s,n,1600U,1600U)==FOC_OC_CLEAR); }

static void alignment(void)
{
    FocFeedbackSafety s=fixture(); FocFeedbackFrame f;
    for (uint32_t n=1U;n<=3U;++n) {
        assert(push(&s,n,(uint16_t)(1600U+n),1600U)==FOC_OC_CLEAR);
        assert(!take(&s,&f));
    }
    assert(push(&s,4U,1604U,1600U)==FOC_OC_CLEAR);
    assert(take(&s,&f));
    assert(f.source_seq==3U && f.source_us==150U && f.u==1603U);
    assert(f.measurement_angle==3.0f && f.actuation_angle==4.0f);
    assert(fabsf(f.iu_A+0.03f)<0.00001f && f.repaired_mask==0U);
    assert(fabsf(f.iw_A-0.03f)<0.00001f);
    assert(!take(&s,&f) && !f.ready);
    for (uint32_t n=5U;n<=100U;++n) {
        assert(push(&s,n,1600U,1600U)==FOC_OC_CLEAR);
        assert(take(&s,&f));
        assert(f.source_seq==n-1U && f.source_us==(n-1U)*50U);
        assert(f.measurement_angle==(float)(n-1U) && f.actuation_angle==(float)n);
    }
}
static void spike_and_step(void)
{
    FocFeedbackSafety s=fixture(); FocFeedbackFrame f;
    assert(push(&s,1U,1600U,1600U)==FOC_OC_CLEAR);
    assert(push(&s,2U,1600U,1600U)==FOC_OC_CLEAR);
    /* 16 A raw excursion: current sample is warm-up; repaired next period. */
    assert(push(&s,3U,0U,1600U)==FOC_OC_CLEAR);
    assert(push(&s,4U,1600U,1600U)==FOC_OC_CLEAR);
    assert(take(&s,&f));
    assert(f.source_seq==3U && f.u==1600U && f.iu_A==0.0f && f.repaired_mask==1U);
    assert(s.protection.repaired_pairs==1U);
    /* This also erases an identical REAL one-period pulse. Hardware protection
     * must remain independent; this test cannot label the pulse as noise. */
    s=fixture(); warm(&s);
    assert(push(&s,5U,1100U,1600U)==FOC_OC_CLEAR);
    assert(push(&s,6U,1100U,1600U)==FOC_OC_PENDING);
    assert(take(&s,&f) && f.repaired_mask==0U && f.iu_A==5.0f);
    assert(push(&s,7U,1100U,1600U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_CONFIRMED_CURRENT);
    assert(s.protection.trip_mask==5U && !take(&s,&f));
    assert(push(&s,8U,1600U,1600U)==FOC_OC_TRIPPED);
}
static void faults(void)
{
    FocFeedbackSafety s=fixture(); FocFeedbackFrame f; warm(&s);
    assert(FocFeedbackSafety_Poll(&s,200U,FOC_FP_HW_TRIP,1U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_HARDWARE && !take(&s,&f));
    assert(FocFeedbackSafety_Poll(&s,200U,FOC_FP_DRIVER_FAULT,1U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_HARDWARE && s.protection.fault_flags==3U);
    s=fixture(); warm(&s);
    assert(FocFeedbackSafety_Poll(&s,200U,0U,0U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_HEALTH && s.protection.fault_flags==FOC_FB_OUTPUT_LOCK_LOST);
    s=fixture(); assert(push(&s,1U,4096U,1600U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_RAW_INVALID);
    s=fixture(); assert(FocFeedbackSafety_Push(&s,1U,50U,1600U,1600U,NAN,0U,1U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_FEEDBACK_INVALID);
    s=fixture(); assert(FocFeedbackSafety_Poll(&s,0U,FOC_FP_ZERO_INVALID,1U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_HEALTH);
    s=fixture(); warm(&s);
    assert(!FocFeedbackSafety_Take(&s,200U,FOC_FP_DRIVER_FAULT,1U,&f) && !f.ready);
    assert(s.protection.reason==FOC_FP_HARDWARE);
}
static void continuity(void)
{
    FocFeedbackSafety s=fixture(); FocFeedbackFrame f; warm(&s);
    assert(FocFeedbackSafety_Poll(&s,300U,0U,1U)==FOC_OC_CLEAR);
    assert(FocFeedbackSafety_Poll(&s,301U,0U,1U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_TIMEOUT && !take(&s,&f));
    s=fixture(); warm(&s);
    assert(!FocFeedbackSafety_Take(&s,301U,0U,1U,&f) && !f.ready);
    assert(s.protection.reason==FOC_FP_TIMEOUT);
    s=fixture(); warm(&s); assert(push(&s,6U,1600U,1600U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_SEQUENCE);
    s=fixture(); warm(&s); assert(push(&s,4U,1600U,1600U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_SEQUENCE);
    s=fixture();
    assert(FocFeedbackSafety_Begin(&s,s.cfg,UINT32_MAX-99U)==FOC_OC_CLEAR);
    for (uint32_t n=0U;n<6U;++n) {
        uint32_t seq=UINT32_MAX-2U+n, us=UINT32_MAX-49U+n*50U;
        assert(FocFeedbackSafety_Push(&s,seq,us,1600U,1600U,(float)n,0U,1U)==FOC_OC_CLEAR);
        if (n>=3U) {
            assert(take(&s,&f));
            assert(f.source_seq==seq-1U && f.source_us==us-50U);
        }
    }
}
static void repair_quality(void)
{
    FocFeedbackSafety s=fixture();
    /* Four well-separated repairs exceed the 3/32 quality budget. No current
     * trip: these are repaired to zero current, not named overcurrent. */
    for (uint32_t n=1U;n<=14U;++n) {
        uint16_t u=(n==3U || n==6U || n==9U || n==12U)?1000U:1600U;
        FocOcConfirmResult r=push(&s,n,u,1600U);
        if (n<13U) assert(r==FOC_OC_CLEAR);
        else assert(r==FOC_OC_TRIPPED);
    }
    assert(s.protection.reason==FOC_FP_REPAIR_BUDGET && s.protection.repaired_pairs==4U);
    assert(s.protection.trip_mask==0U && !s.frame.ready);
}
static void config(void)
{
    FocFeedbackSafety s=fixture(); FocFeedbackSafetyConfig cfg=s.cfg;
    cfg.zero_u=4096U; assert(FocFeedbackSafety_Begin(&s,cfg,0U)==FOC_OC_TRIPPED);
    assert(s.protection.reason==FOC_FP_CONFIG);
    cfg.zero_u=1600U; cfg.count_to_A=NAN;
    assert(FocFeedbackSafety_Begin(&s,cfg,0U)==FOC_OC_TRIPPED);
    cfg.count_to_A=0.0f; assert(FocFeedbackSafety_Begin(&s,cfg,0U)==FOC_OC_TRIPPED);
    cfg.count_to_A=-0.1f; assert(FocFeedbackSafety_Begin(&s,cfg,0U)==FOC_OC_TRIPPED);
    cfg.count_to_A=INFINITY; assert(FocFeedbackSafety_Begin(&s,cfg,0U)==FOC_OC_TRIPPED);
}
int main(int argc,char **argv)
{
    assert(argc==2);
    switch (atoi(argv[1])) {
    case 0: alignment(); break; case 1: spike_and_step(); break;
    case 2: faults(); break; case 3: continuity(); break;
    case 4: repair_quality(); break; case 5: config(); break;
    default: return 2;
    }
    return 0;
}
