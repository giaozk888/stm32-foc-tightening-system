#ifndef FOC_PREEMPT_PROBE_H
#define FOC_PREEMPT_PROBE_H
#include <stdint.h>
#ifndef FOC_HEAVY_PROFILE_ENABLE
#define FOC_HEAVY_PROFILE_ENABLE 1
#endif
#if FOC_HEAVY_PROFILE_ENABLE != 0 && FOC_HEAVY_PROFILE_ENABLE != 1
#error FOC_HEAVY_PROFILE_ENABLE must be 0 or 1
#endif
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
#if !defined(FOC_ONE_CYCLE_PWM_PIPELINE) || !defined(AS5047P_DMA_FOC_FIRST) || \
    !defined(FOC_PROTECTED_CLOSED_LOOP) || !defined(FOC_LATEST_ORIGINAL_FSM) || \
    !defined(FOC_ADC_RC_PROTECTED_CANDIDATE) || defined(FOC_FAST_REJECT_COMPUTE_ONLY) || \
    (defined(FOC_ENABLE_LEGACY_CURRENT_REPAIR) && FOC_ENABLE_LEGACY_CURRENT_REPAIR)
#error Pipeline closed-loop candidate requires the complete protected original-FSM backend
#endif
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
#if !defined(FOC_PREEMPT_COMMIT_PROBE) || \
    (!defined(FOC_FAST_REJECT_COMPUTE_ONLY) && !defined(FOC_PWM_PIPELINE_CLOSED_LOOP))
#error One-cycle PWM preparation requires the exclusive hard-off diagnostic
#endif
#define FOC_SOFTWARE_GUARD_PRIORITY 3U
#else
#define FOC_SOFTWARE_GUARD_PRIORITY 0U
#endif

/* Legacy attribution: GUARD(0) > encoder(1) > ADC(2).
 * One-cycle preparation: encoder(1) > ADC(2) > software GUARD(3).
 * TIM7 is then a service-wall counter, NOT an ADC preemption contributor.
 * Equal-priority encoder sources cannot nest. Hooks never mask IRQs. */
enum { FOC_PRE_GUARD, FOC_PRE_TIMER, FOC_PRE_RX, FOC_PRE_TX, FOC_PRE_N };
typedef struct { uint32_t cycles, count, max_single, invalid; } FocPreIrq;
typedef struct { uint32_t dwt, guard_cycles, valid; } FocPreToken;
typedef struct {
    uint32_t dwt, cycles[4], count[4], errors, valid;
    uint32_t tim1_cnt, tim1_dir, timer_span;
} FocPreStamp;
typedef struct {
    uint32_t wall, preempt, active_est, cycles[4], count[4], valid, dominant, path;
} FocPreFrame;
typedef struct {
    uint32_t frames, invalid, wall_max, preempt_max, active_est_max;
    uint32_t deadline_miss, observer_tail_max;
    FocPreFrame worst_preempt, first_miss;
} FocPreTiming;
/* Separate schema; do not reinterpret the historic first_miss RAM layout.
 * captured is set even if attribution fails the inventory/identity
 * checks; valid must NEVER be forced true merely because a deadline missed. */
typedef struct {
    uint32_t captured, valid, wall_cycles, active_est_cycles;
    uint32_t tim2_cycles, tim2_count, dma_rx_cycles, dma_rx_count;
    uint32_t other_irq_cycles, other_irq_count, preempt_total_cycles;
    uint32_t tim1_cnt, tim1_dir, dwt_entry, dwt_exit, timer_span;
} FocDeadlineSnapshot;

/* Fixed-work per-source subtraction. Exclusive totals avoid double counting
 * GUARD nested inside encoder IRQ. CPU estimate retains exception overhead
 * outside hooks AND instrumentation; it is not a pure mathematical FOC WCET. */
static inline void FocPre_Delta(FocPreFrame *f,const FocPreStamp *a,
                               const FocPreStamp *b)
{
    f->wall=b->dwt-a->dwt;
#define FOC_PRE_DIFF(i) f->cycles[i]=b->cycles[i]-a->cycles[i]; \
    f->count[i]=b->count[i]-a->count[i]
    FOC_PRE_DIFF(0); FOC_PRE_DIFF(1); FOC_PRE_DIFF(2); FOC_PRE_DIFF(3);
#undef FOC_PRE_DIFF
    f->preempt=f->cycles[0]+f->cycles[1]+f->cycles[2]+f->cycles[3];
    f->valid=a->valid && b->valid && a->errors==b->errors && f->preempt<=f->wall;
    f->active_est=f->valid ? f->wall-f->preempt : 0U;
    f->dominant=0U;
    if (f->cycles[1]>f->cycles[f->dominant]) f->dominant=1U;
    if (f->cycles[2]>f->cycles[f->dominant]) f->dominant=2U;
    if (f->cycles[3]>f->cycles[f->dominant]) f->dominant=3U;
}

#if defined(FOC_PREEMPT_COMMIT_PROBE)
#if (!defined(FOC_FAST_REJECT_COMPUTE_ONLY) && !defined(FOC_PWM_PIPELINE_CLOSED_LOOP)) || \
    !defined(FOC_FAST_CURRENT_REJECT) || \
    !defined(AS5047P_DMA_IRQ_PREEMPT_ADC) || defined(FOC_FAST_PATH_PROFILE) || \
    defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE) || \
    defined(FOC_PWM_BOUNDARY_LITE) || defined(FOC_RC_DEFERRED_SHADOW)
#error Preemption/commit probe requires the separate fast-current hard-off profile
#endif
extern volatile FocPreIrq foc_preempt_irq[4];
extern volatile FocPreTiming foc_preempt_timing;
extern volatile FocDeadlineSnapshot deadline_snapshot;
extern volatile uint32_t foc_stamp_assisted_count;
extern volatile uint32_t foc_probe_priorities_ok, foc_probe_unexpected_irq;
FocPreToken FocPreempt_IrqBegin(unsigned source);
void FocPreempt_IrqEnd(unsigned source,FocPreToken token);
uint32_t FocPreempt_Begin(void);
uint32_t FocPreempt_End(uint32_t start,uint32_t path);
void FocPreempt_CheckPriorities(void); /* Task only, read-only NVIC inventory. */
void FocPreempt_Monitor(void); /* Task only; formatting never in ISR. */
#endif
#endif
