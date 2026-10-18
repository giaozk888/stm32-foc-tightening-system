#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "foc_feedback_safety_candidate.h"
static FocFeedbackSafety s;
static uint32_t seq, now;
static void init(void)
{
    seq=0U; now=0U;
    foc_current_fault_trace=(FocCurrentTrace){0};
    foc_current_trace_frame=0;
    foc_current_trace_pwm_pending=0U;
    FocFeedbackSafetyConfig cfg={.protection={4.0f,100U,100U,6U,4U},
        .zero_u=1564U,.zero_v=1561U,.count_to_A=3300.0f/(4095.0f*120.0f)};
    assert(FocFeedbackSafety_Begin(&s,cfg,now)==FOC_OC_CLEAR);
    assert(s.raw_trip_counts==595U && FOC_OC_TRIPPED==2U);
}
static FocOcConfirmResult pair(uint16_t u,uint16_t v)
{
    FocOcConfirmResult result=FocFeedbackSafety_Push(&s,++seq,now+=50U,u,v,.25f,0U,1U);
    FocFeedbackFrame out;
    if (result!=FOC_OC_TRIPPED && FocFeedbackSafety_Take(&s,now,0U,1U,&out)) {
        FocCurrentTrace_Pi(); FocCurrentTrace_Pwm();
    }
    FocCurrentTrace_End();
    return result;
}
static FocCurrentTraceFrame *last(void)
{ return &foc_current_fault_trace.frames[foc_current_fault_trace.current_index]; }
int main(int argc,char **argv)
{
    init();
    for (unsigned i=0U;i<24U;++i) assert(pair(1564,1561)==FOC_OC_CLEAR);
    assert(foc_current_fault_trace.count==16U && foc_current_fault_trace.write_index==8U);
    assert(last()->discriminator_executed && last()->discriminator_result==1);
    assert(!last()->pi_frozen && !last()->pwm_frozen && !last()->hardware_valid);
    assert(pair(1018,2166)==FOC_OC_PENDING);
    assert(last()->events==FOC_TRACE_TRIGGER);
    assert(last()->iu_counts==546 && last()->iv_counts==-605 && last()->iw_counts==59);
    assert(last()->over_mask==2U && last()->limit_counts==595U);
    assert(last()->discriminator_executed && last()->discriminator_result==0);
    assert(last()->pi_frozen && last()->pwm_frozen);
    for (unsigned i=0U;i<3U;++i) assert(pair(1018,2166)==FOC_OC_PENDING);
    uint32_t samples=s.validation.current_samples_total;
    assert(pair(1018,2166)==FOC_OC_TRIPPED);
    assert(s.validation.current_samples_total==samples); /* Not executed on fault frame. */
    assert(!last()->discriminator_executed && last()->discriminator_result==-2);
    assert(last()->protection_fault && last()->confirm_cycles==4U && !last()->good_samples);
    assert(!foc_current_fault_trace.frozen && !foc_current_fault_trace.fault_seq);
    assert(last()->pi_frozen && last()->pwm_frozen);
    init();
    for (unsigned run=0U;run<100U;++run) {
        for (unsigned i=0U;i<20U;++i) pair(1564,1561);
        assert(pair(1018,2166)==FOC_OC_PENDING);
        assert(pair(1564,1561)==FOC_OC_PENDING && last()->good_samples==1U);
        assert(pair(1564,1561)==FOC_OC_CLEAR && last()->events==FOC_TRACE_RECOVERY);
        assert(!foc_current_fault_trace.frozen);
    }
    assert(s.protection.cur_confirm_enter_count==100U);
    assert(s.protection.cur_confirm_clear_count==100U);
    for (unsigned i=0U;i<500000U;++i) assert(pair(1564,1561)==FOC_OC_CLEAR);
    /* Four real calls: initial suspicion, then three inexplicable samples.
     * No forced state, counter, reference or threshold changes. */
    assert(pair(1740,1561)==FOC_OC_CLEAR);
    assert(pair(1300,1561)==FOC_OC_CLEAR);
    assert(pair(1900,1561)==FOC_OC_CLEAR);
    FocCurrentTrace_Pending(1U);
    assert(pair(1200,1561)==FOC_OC_TRIPPED);
    assert(foc_current_fault_trace.frozen && foc_current_fault_trace.freeze_reason==1U);
    assert(foc_current_fault_trace.count==16U && foc_current_fault_trace.fault_seq==seq);
    assert(last()->reference_u_before==1564U && last()->reference_v_before==1561U);
    assert(last()->candidate_u_before==1900U && last()->candidate_v_before==1561U);
    assert(last()->d_old==364U && last()->d_candidate==700U);
    assert(last()->unresolved_consecutive_before==2U && last()->state_before==FOC_CURRENT_SUSPECT);
    assert(last()->pwm_pending_before==2U && last()->decision_path==FOC_CURRENT_PATH_UNRESOLVED);
    assert(s.validation.candidate.u==1200U); /* Post-state differs; before survived. */
    for (unsigned i=0U;i<16U;++i) {
        unsigned slot=(foc_current_fault_trace.write_index+i)&15U;
        FocCurrentTraceFrame *f=&foc_current_fault_trace.frames[slot];
        assert(f->seq==seq-15U+i);
        if (i>=13U) {
            assert(f->decision_path==FOC_CURRENT_PATH_UNRESOLVED);
            assert(f->unresolved_consecutive_before==i-13U);
        }
    }
    FocCurrentTrace saved=foc_current_fault_trace;
    for (unsigned i=0U;i<100U;++i) assert(pair(1564,1561)==FOC_OC_TRIPPED);
    assert(!memcmp(&saved,&foc_current_fault_trace,sizeof saved));
    if (argc==2) {
        FILE *dump=fopen(argv[1],"wb");
        assert(dump && fwrite(&saved,sizeof saved,1U,dump)==1U);
        assert(fclose(dump)==0);
    }

    init(); seq=UINT32_MAX-5U;
    for (unsigned i=0U;i<5U;++i) pair(1564,1561);
    pair(1018,2166); /* Trigger seq wraps to zero: flag, not seq, owns validity. */
    assert(!last()->seq && last()->events==FOC_TRACE_TRIGGER);
    pair(1564,1561); pair(1564,1561);
    for (unsigned i=0U;i<4U;++i) pair(1564,1561);
    assert(!foc_current_fault_trace.frozen && last()->seq==6U);

    init(); pair(1564,1561);
    assert(FocFeedbackSafety_Push(&s,++seq,now+=50U,1564,1561,.25f,
        FOC_FP_HW_TRIP,1U)==FOC_OC_TRIPPED);
    assert(!foc_current_fault_trace.frozen && last()->protection_fault);
    assert(!last()->compare_executed && !last()->discriminator_executed);

    /* Discriminator failure is recorded AFTER its real return, not by the
     * removed generic Trip hook. The core's control outcome is unchanged. */
    init();
    s.validation.state=FOC_CURRENT_SUSPECT;
    s.validation.candidate=(CurrentRawPair){2200,1561};
    s.validation.current_unresolved_consecutive=2U;
    assert(pair(1800,1561)==FOC_OC_TRIPPED);
    assert(foc_current_fault_trace.frozen && last()->protection_fault);
    assert(last()->discriminator_executed && last()->discriminator_result==-1);
    assert(last()->protection_reason==FOC_FP_CURRENT_INVALID);
    assert(last()->candidate_u_before==2200U && last()->reference_u_before==1564U);
    assert(last()->d_old==236U && last()->d_candidate==400U);

    /* Other protection reasons stay recorded but cannot freeze this ring. */
    init();
    assert(FocFeedbackSafety_Push(&s,1U,50U,1564,1561,.25f,0U,1U)==FOC_OC_CLEAR);
    FocFeedbackFrame out;
    assert(!FocFeedbackSafety_Take(&s,151U,0U,1U,&out));
    assert(!foc_current_fault_trace.frozen && last()->protection_fault);
    assert(last()->discriminator_executed && last()->protection_reason==FOC_FP_TIMEOUT);
    /* Force a ring reuse after USE, with discriminator skipped by hardware
     * safety: decision, path, PI and PWM flags must all start fresh. */
    init();
    for (unsigned i=0U;i<16U;++i) pair(1564,1561);
    assert(FocFeedbackSafety_Push(&s,++seq,now+=50U,1564,1561,.25f,
        FOC_FP_HW_TRIP,1U)==FOC_OC_TRIPPED);
    assert(!last()->discriminator_executed && last()->discriminator_result==-2);
    assert(last()->decision_path==FOC_CURRENT_PATH_NONE && last()->pi_frozen && last()->pwm_frozen);
    /* A real fault at wrapped seq=0 is still a valid frozen capture. */
    init(); seq=UINT32_MAX-3U;
    pair(1740,1561); pair(1300,1561); pair(1900,1561);
    assert(pair(1200,1561)==FOC_OC_TRIPPED);
    assert(foc_current_fault_trace.frozen && !foc_current_fault_trace.fault_seq);
    puts("PASS trace: rolling CUR_CONFIRM, long-run final unresolved window, before-state, immutable fault, fresh skipped decision");
    return 0;
}
