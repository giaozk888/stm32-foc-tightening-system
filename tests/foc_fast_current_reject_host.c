/* Production selector/safety regressions. Synthetic inputs, not board timing. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "foc_feedback_safety_candidate.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
static FocFeedbackSafety s;
static uint32_t seq,now;
static void begin_at(uint16_t u,uint16_t v)
{
    seq=0U; now=0U;
    FocFeedbackSafetyConfig cfg={ .protection={4.0f,100U,100U,6U,4U},
        .zero_u=u,.zero_v=v,.count_to_A=3300.0f/(4095.0f*120.0f) };
    CHECK(FocFeedbackSafety_Begin(&s,cfg,now)==FOC_OC_CLEAR);
    CHECK(s.raw_trip_counts==595U);
}
static void begin(void) { begin_at(1560,1560); }
static int push(uint16_t u,uint16_t v)
{
    FocFeedbackFrame frame;
    now+=50U; ++seq;
    FocOcConfirmResult r=FocFeedbackSafety_Push(&s,seq,now,u,v,.25f,0U,1U);
    int ready=FocFeedbackSafety_Take(&s,now,0U,1U,&frame);
    if (ready) {
        CHECK(frame.u==u && frame.v==v && frame.source_seq==seq && frame.source_us==now);
        CHECK(frame.measurement_angle==frame.actuation_angle && !frame.repaired_mask);
        CHECK(frame.iw_A==-(frame.iu_A+frame.iv_A));
    } else CHECK(!frame.ready && !s.frame.ready);
    return r==FOC_OC_TRIPPED ? -1 : ready;
}
static void no_fault(void) { CHECK(!s.validation.current_measurement_fault_count && s.protection.result!=FOC_OC_TRIPPED); }
static void reference(uint16_t u,uint16_t v)
{ CHECK(s.validation.reference.u==u && s.validation.reference.v==v); }
int main(void)
{
    /* 1. Steady normal. */
    begin(); CHECK(push(1560,1560)==1 && push(1561,1561)==1 && push(1559,1559)==1 && push(1562,1562)==1);
    CHECK(!s.validation.current_suspect_total && !s.validation.current_confirmed_spike && !s.validation.current_confirmed_transition); no_fault();
    /* 2/3. Positive/negative isolated impulse; current pair is never repaired. */
    begin(); CHECK(push(1560,1560)==1 && push(1561,1561)==1 && push(1740,1740)==0);
    reference(1561,1561); CHECK(s.validation.state==FOC_CURRENT_SUSPECT);
    CHECK(push(1562,1562)==1 && push(1561,1561)==1);
    CHECK(s.validation.current_confirmed_spike==1U && !s.validation.current_unresolved_total); no_fault();
    begin(); CHECK(push(1560,1560)==1 && push(1559,1559)==1 && push(1380,1380)==0 && push(1561,1561)==1);
    CHECK(s.validation.current_confirmed_spike==1U); no_fault();
    /* 4/5. Real step and outward ramp: one held cycle then rebase. */
    begin(); CHECK(push(1560,1560)==1 && push(1562,1562)==1 && push(1630,1630)==0 && push(1634,1634)==1 && push(1636,1636)==1);
    CHECK(s.validation.current_confirmed_transition==1U); reference(1636,1636); no_fault();
    begin(); CHECK(push(1560,1560)==1 && push(1562,1562)==1 && push(1630,1630)==0 && push(1680,1680)==1 && push(1720,1720)==1);
    CHECK(s.validation.current_confirmed_transition==1U); reference(1720,1720); no_fault();
    /* 6. Actual observed endpoints; missing intermediate window is synthetic. */
    begin_at(1626,1609); CHECK(push(1560,1557)==0 && push(1561,1558)==1 && push(1562,1559)==1);
    CHECK(s.validation.current_confirmed_transition==1U && !s.validation.current_unresolved_total);
    reference(1562,1559); no_fault();
    begin_at(1563,1561); CHECK(push(1594,1585)==1 && push(1626,1609)==1);
    CHECK(push(1560,1557)==0 && push(1560,1557)==1 && push(1560,1557)==1); no_fault();
    /* 7. Incoherent alternating values. Suspect itself is NOT unresolved #1. */
    begin(); CHECK(push(1560,1560)==1 && push(1750,1750)==0);
    CHECK(!s.validation.current_unresolved_consecutive);
    CHECK(push(1410,1410)==0 && push(1800,1800)==0 && push(1300,1300)==-1);
    CHECK(s.validation.current_unresolved_total==3U && s.validation.current_unresolved_max_consecutive==3U);
    CHECK(s.validation.current_measurement_fault_count==1U && s.protection.reason==FOC_FP_CURRENT_INVALID);
    CHECK(push(1560,1560)==-1 && s.validation.current_measurement_fault_count==1U); reference(1560,1560);
    /* 8/9/10. Each ADC event is ONE atomic U/V pair, including both abnormal. */
    for (unsigned channel=1;channel<=3;++channel) {
        begin(); CHECK(push(channel&1U?1740:1561,channel&2U?1740:1561)==0);
        CHECK(s.validation.current_suspect_total==1U); reference(1560,1560);
        CHECK(push(1562,1562)==1 && s.validation.current_confirmed_spike==1U);
        reference(1562,1562); no_fault();
    }
    /* Exact jump accepted, return tolerance inclusive. */
    begin(); CHECK(push(1620,1500)==1); reference(1620,1500);
    CHECK(push(1740,1500)==0 && push(1645,1500)==1 && s.validation.current_confirmed_spike==1U);
    /* Two unrelated spikes closer than old but still >60 apart stay unresolved. */
    begin(); CHECK(push(1750,1560)==0 && push(1950,1560)==0);
    CHECK(s.validation.current_unresolved_consecutive==1U); reference(1560,1560);
    CHECK(push(1560,1560)==1 && !s.validation.current_unresolved_consecutive);
    CHECK(!s.validation.current_confirmed_spike && s.validation.current_recovered_after_unresolved==1U); no_fault();
    begin(); CHECK(push(1630,1560)==0 && push(1595,1560)==0); /* equidistant */
    CHECK(s.validation.current_unresolved_consecutive==1U);
    CHECK(push(1596,1560)==1 && s.validation.current_confirmed_transition==1U); no_fault();
    begin(); for (unsigned i=0;i<100;++i) CHECK(push(1740,1560)==0 && push(1560,1560)==1);
    CHECK(s.validation.current_confirmed_spike==100U && !s.validation.current_unresolved_total); no_fault();
    /* Raw confirmation still sees every pair, including held feedback and W. */
    begin(); CHECK(push(900,1560)==0 && push(1560,1560)==1 && push(900,1560)==0);
    CHECK(!s.protection.good_samples && s.protection.confirm_cycles==2U);
    CHECK(push(1560,1560)==1 && push(1560,1560)==1);
    CHECK(s.protection.cur_confirm_clear_count==1U && !s.protection.pending);
    begin(); CHECK(push(1200,1200)==0);
    for (unsigned i=1U;i<CUR_CONFIRM_MAX_CYCLES;++i) CHECK(push(1200,1200)==1);
    CHECK(push(1200,1200)==-1);
    CHECK(s.protection.reason==FOC_FP_TIMEOUT && s.protection.trip_mask==4U);
    CHECK(s.protection.timeout.reason==FOC_TO_CURRENT_CONFIRM);
    begin(); CHECK(push(900,1560)==0 && push(1560,1560)==1 && push(1560,1560)==1);
    CHECK(s.protection.result==FOC_OC_CLEAR && !s.protection.pending);
    begin(); CHECK(push(4096,1560)==-1 && s.protection.reason==FOC_FP_RAW_INVALID);
    begin(); CHECK(FocFeedbackSafety_Push(&s,1,50,1560,1560,0,FOC_FP_DRIVER_FAULT,1)==FOC_OC_TRIPPED);
    CHECK(s.protection.reason==FOC_FP_HARDWARE);
    begin(); CHECK(FocFeedbackSafety_Push(&s,1,50,1560,1560,0,0,0)==FOC_OC_TRIPPED);
    begin(); CHECK(push(1560,1560)==1 && FocFeedbackSafety_Poll(&s,151,0,1)==FOC_OC_TRIPPED);
    begin(); CHECK(push(1560,1560)==1); ++seq;
    CHECK(push(1560,1560)==-1 && s.protection.reason==FOC_FP_SEQUENCE);
    begin(); CHECK(FocFeedbackSafety_Push(&s,1,50,1560,1560,NAN,0,1)==FOC_OC_TRIPPED);
    begin(); now=UINT32_MAX-24U; s.protection.begin_us=now;
    CHECK(push(1560,1560)==1 && push(1700,1560)==0 && push(1560,1560)==1);
    FocCurrentCycleStats cycles={0};
    CHECK(!FocCurrentCycles_Record(&cycles,5000,FOC_CURRENT_PATH_NORMAL));
    CHECK(!FocCurrentCycles_Record(&cycles,700,FOC_CURRENT_PATH_SUSPECT));
    CHECK(!FocCurrentCycles_Record(&cycles,800,FOC_CURRENT_PATH_UNRESOLVED));
    CHECK(!FocCurrentCycles_Record(&cycles,8499,0));
    CHECK(FocCurrentCycles_Record(&cycles,8500,FOC_CURRENT_PATH_UNRESOLVED));
    CHECK(cycles.normal_max_cycles==5000 && cycles.suspect_max_cycles==700 && cycles.unresolved_max_cycles==8500 && cycles.deadline_miss_count==1);
    s.validation.current_samples_total=UINT32_MAX;
    FocCurrentValidation_Push(&s.validation,1560,1560);
    CHECK(s.validation.current_samples_total==UINT32_MAX);
    puts("PASS 10 discriminator cases, reference rebase, unresolved-only fault, raw safety and profiling");
    return 0;
}
