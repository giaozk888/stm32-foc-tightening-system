#include "foc_current_fault_trace.h"
#if FOC_CURRENT_FAULT_TRACE_ENABLE
#include "foc_feedback_safety_candidate.h"
#include <string.h>
#if !defined(FOC_TRACE_HOST_TEST)
#include "main.h"
#endif

/* .bss only. No startup constructor/reset, and no extra RAM in the control
 * state. First Begin writes the schema. A reset re-arms diagnostics only. */
FocCurrentTrace foc_current_fault_trace;
FocCurrentTraceFrame *foc_current_trace_frame;
uint8_t foc_current_trace_pwm_pending;

static __attribute__((noinline)) void trace_before(
    FocCurrentTraceFrame *f,const FocCurrentValidation *v)
{
    memcpy(&f->reference_u_before,&v->reference,2U*sizeof(CurrentRawPair));
    CurrentRawPair raw={f->raw_u,f->raw_v};
    f->d_old=(uint16_t)FocCurrentValidation_Distance(raw,v->reference);
    f->d_candidate=(uint16_t)FocCurrentValidation_Distance(raw,v->candidate);
    f->unresolved_consecutive_before=v->current_unresolved_consecutive;
    f->state_before=v->state;
    f->pwm_pending_before=foc_current_trace_pwm_pending;
    f->decision_path=FOC_CURRENT_PATH_NONE; /* Reserved remains zero-initialized. */
}

void FocCurrentTrace_Begin(uint32_t seq,uint32_t now,uint16_t u,uint16_t v,
    const FocFeedbackSafety *s,float angle)
{
    FocCurrentTrace *t=&foc_current_fault_trace;
    if (t->frozen) return;
    t->magic=FOC_TRACE_MAGIC; t->frame_bytes=sizeof(FocCurrentTraceFrame);
    t->capacity=FOC_TRACE_FRAMES;
    t->current_index=t->write_index;
    FocCurrentTraceFrame *f=&t->frames[t->current_index];
    foc_current_trace_frame=f;
    f->seq=seq; f->sample_us=now; f->raw_u=u; f->raw_v=v;
    memcpy(&f->zero_u,&s->cfg.zero_u,2U*sizeof(uint16_t));
    f->limit_counts=s->raw_trip_counts;
    f->electrical_angle=angle;
    /* Compare owns current counts; compare_executed=0 makes them unavailable
     * rather than presenting a reused slot's old counts as a new measurement. */
    f->state_words[0]=0U; f->state_words[1]=0U;
    f->state_words[2]=UINT32_C(0xfe000000); /* discriminator NOT_EXECUTED */
    f->state_words[3]=UINT32_C(0x101)|((uint32_t)s->protection.pending<<24U);
    trace_before(f,&s->validation);
#if !defined(FOC_TRACE_HOST_TEST)
    /* Compare PRELOAD register readback at pair processing, not active shadow
     * or proof of the ADC sampling aperture. No timer behavior is changed. */
    f->ccr1=(uint16_t)TIM1->CCR1; f->ccr2=(uint16_t)TIM1->CCR2;
    f->ccr3=(uint16_t)TIM1->CCR3; f->timer_cnt=(uint16_t)TIM1->CNT;
    f->timer_down=(TIM1->CR1 & TIM_CR1_DIR)!=0U; f->hardware_valid=1U;
#else
    f->ccr1=0U; f->ccr2=0U; f->ccr3=0U; f->timer_cnt=0U;
    f->timer_down=0U; f->hardware_valid=0U;
#endif
    t->write_index=(uint8_t)((t->write_index+1U)&15U);
    if (t->count<FOC_TRACE_FRAMES) ++t->count;
    t->open=1U;
}
void FocCurrentTrace_Protection(const FocFilteredProtection *p)
{
    FocCurrentTrace *t=&foc_current_fault_trace;
    FocCurrentTraceFrame *f=foc_current_trace_frame;
    if (!f) return;
    f->confirm_active=p->pending; f->confirm_cycles=p->confirm_cycles; f->good_samples=p->good_samples;
    f->protection_result=p->result; f->protection_reason=p->reason;
    f->protection_fault=(p->result==FOC_OC_TRIPPED);
    if (p->pending!=f->pending_before)
        f->events=(uint8_t)(2U-p->pending); /* 1=entry, 2=recovery. */
    /* The discriminator context is already recorded. Only the real, latched
     * CURRENT_INVALID reason owns freeze; confirmation/recovery never does. */
    if (!f->protection_fault || p->reason!=FOC_FP_CURRENT_INVALID) return;
    t->fault_seq=f->seq;
    t->freeze_reason=1U; t->open=0U;
    foc_current_trace_frame=0;
#if defined(__arm__)
        __asm__ volatile("dmb" ::: "memory");
#else
        __asm__ volatile("" ::: "memory");
#endif
    t->frozen=1U;
}
#endif /* FOC_CURRENT_FAULT_TRACE_ENABLE */
