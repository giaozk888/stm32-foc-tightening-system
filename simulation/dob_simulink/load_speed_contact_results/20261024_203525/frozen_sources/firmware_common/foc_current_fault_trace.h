#ifndef FOC_CURRENT_FAULT_TRACE_H
#define FOC_CURRENT_FAULT_TRACE_H
#include <stdint.h>
#ifndef FOC_CURRENT_FAULT_TRACE_ENABLE
#define FOC_CURRENT_FAULT_TRACE_ENABLE 0
#endif
#if FOC_CURRENT_FAULT_TRACE_ENABLE != 0 && FOC_CURRENT_FAULT_TRACE_ENABLE != 1
#error FOC_CURRENT_FAULT_TRACE_ENABLE must be 0 or 1
#endif

/* Diagnostic-only, single ADC owner. Dump ONLY a halted capture or a frozen
 * ring. No policy, allocation, IO, timer writes, or reconstructed ADC-W. */
#define FOC_TRACE_FRAMES 16U
#define FOC_TRACE_MAGIC UINT32_C(0x43545232) /* CTR2: before-state, rolling. */
enum { FOC_TRACE_TRIGGER=1U, FOC_TRACE_RECOVERY=2U };
typedef struct {
    union {
        struct {
            uint8_t timer_down, hardware_valid, compare_executed, over_mask;
            uint8_t confirm_active, confirm_cycles, good_samples, protection_fault;
            uint8_t protection_result, protection_reason, discriminator_executed;
            int8_t discriminator_result; /* -2=not executed, -1=fault, 0=hold, 1=use. */
            uint8_t pi_frozen, pwm_frozen, events, pending_before;
        };
        uint32_t state_words[4]; /* Fixed little-endian diagnostic initialization. */
    };
    uint32_t seq, sample_us;
    uint16_t raw_u, raw_v, zero_u, zero_v, limit_counts;
    int16_t iu_counts, iv_counts, iw_counts;
    uint16_t ccr1, ccr2, ccr3, timer_cnt;
    float electrical_angle; /* Existing prediction, radians, no conversion. */
    /* Captured before Push can replace candidate/reference. Distances are
     * exact integer pair distances, not reconstructed from the fault end-state. */
    uint16_t reference_u_before, reference_v_before;
    uint16_t candidate_u_before, candidate_v_before;
    uint16_t d_old, d_candidate;
    uint32_t unresolved_consecutive_before;
    uint8_t state_before, pwm_pending_before, decision_path, before_reserved;
} FocCurrentTraceFrame;
typedef struct {
    uint32_t magic, fault_seq;
    uint16_t frame_bytes, capacity;
    uint8_t write_index, count, current_index, open;
    uint8_t frozen, freeze_reason, reserved[2];
    FocCurrentTraceFrame frames[FOC_TRACE_FRAMES];
} FocCurrentTrace;
_Static_assert(sizeof(FocCurrentTraceFrame)==72U,"trace ARM/host frame schema");
_Static_assert(sizeof(FocCurrentTrace)==1172U,"trace ring schema");
#if FOC_CURRENT_FAULT_TRACE_ENABLE
extern FocCurrentTrace foc_current_fault_trace;
extern FocCurrentTraceFrame *foc_current_trace_frame;
/* 0=unbound (host/core-only), 1=no pending, 2=valid pending. Not CUR_CONFIRM. */
extern uint8_t foc_current_trace_pwm_pending;
static inline void FocCurrentTrace_Pending(uint8_t valid)
{ foc_current_trace_pwm_pending=(uint8_t)(1U+valid); } /* Pipeline valid is 0/1. */
struct FocFilteredProtection;
struct FocFeedbackSafety;
void FocCurrentTrace_Begin(uint32_t seq,uint32_t now,uint16_t u,uint16_t v,
    const struct FocFeedbackSafety *s,float angle);
void FocCurrentTrace_Protection(const struct FocFilteredProtection *p);
static inline void FocCurrentTrace_End(void)
{
    foc_current_fault_trace.open=0U;
    foc_current_trace_frame=0;
}
static inline void FocCurrentTrace_Compare(int32_t iu,int32_t iv,int32_t iw,uint8_t hit)
{
    FocCurrentTraceFrame *f=foc_current_trace_frame;
    if (f) { f->iu_counts=(int16_t)iu; f->iv_counts=(int16_t)iv;
        f->iw_counts=(int16_t)iw; f->over_mask=hit; f->compare_executed=1U; }
}
static inline void FocCurrentTrace_Discriminator(int result,uint8_t path)
{
    FocCurrentTraceFrame *f=foc_current_trace_frame;
    if (f) { f->discriminator_executed=1U; f->discriminator_result=(int8_t)result;
        f->decision_path=path; }
}
static inline void FocCurrentTrace_Pi(void)
{ if (foc_current_trace_frame) foc_current_trace_frame->pi_frozen=0U; }
static inline void FocCurrentTrace_Pwm(void)
{ if (foc_current_trace_frame) foc_current_trace_frame->pwm_frozen=0U; }
#define FOC_TRACE_CALL(call) call
#else
#define FOC_TRACE_CALL(call) ((void)0)
#endif
#endif
