#include "main.h"
#include "foc_hot_path.h"
#include "foc_preempt_probe.h"
#include "foc_pwm_write_probe.h"
#include "uart_async.h"

volatile FocPreIrq foc_preempt_irq[4];
volatile FocPreTiming foc_preempt_timing;
volatile FocDeadlineSnapshot deadline_snapshot;
volatile uint32_t foc_stamp_assisted_count;
volatile uint32_t foc_probe_priorities_ok, foc_probe_unexpected_irq;
uint32_t foc_probe_irq_priority[7]; /* GUARD TIMER RX TX ADC SysTick PendSV */
#if FOC_HEAVY_PROFILE_ENABLE
static FocPreStamp entry,exit_stamp;
static FocPreFrame frame;
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
uint32_t foc_tim7_preempt_max_cycles;
#endif

/* Each counter has one IRQ writer. The pipeline uses assisted checkpoints;
 * the historic non-pipeline nested-priority experiment retains its old reader. */
#if FOC_HEAVY_PROFILE_ENABLE
#if defined(AS5047P_DMA_FOC_FIRST)
FOC_RAM_PATH static void Stamp(FocPreStamp *s)
{
    s->dwt=DWT->CYCCNT;
    s->tim1_cnt=TIM1->CNT;
    s->tim1_dir=(TIM1->CR1&TIM_CR1_DIR)!=0U;
    s->timer_span=DWT->CYCCNT-s->dwt;
    /* All instrumented writers are BELOW ADC. A suspended writer's partial
     * ledger is not ADC preemption. Inventory checks below prove this premise;
     * do not subtract service wall containing this very ADC from its wall. */
    s->cycles[0]=s->cycles[1]=s->cycles[2]=s->cycles[3]=0U;
    s->count[0]=s->count[1]=s->count[2]=s->count[3]=0U;
    s->errors=0U; s->valid=1U;
}
#elif defined(FOC_ONE_CYCLE_PWM_PIPELINE)
/* IRQ-assisted, wait-free read-side checkpoint. The only contributing writers
 * are equal-priority encoder IRQs (1), all above ADC (2). When one interrupts
 * a reader, its entry hook supplies a coherent alternative BEFORE updating any
 * ledger. Further IRQs cannot replace that alternative. No mask/retry loop,
 * no dropped frame, no moving the exit past an arbitrary retry interval.
 * TIM7(3) cannot interrupt this reader and is deliberately excluded. */
static volatile uint32_t stamp_requested;
static FocPreStamp assisted_stamp;
#ifndef FOC_PRE_CAPTURE_TEST_POINT
#define FOC_PRE_CAPTURE_TEST_POINT(point) ((void)0)
#endif
FOC_RAM_PATH static void Capture(FocPreStamp *s)
{
    FOC_PRE_CAPTURE_TEST_POINT(0);
    s->dwt=DWT->CYCCNT;
    FOC_PRE_CAPTURE_TEST_POINT(1);
    uint32_t dir=TIM1->CR1;
    s->tim1_cnt=TIM1->CNT;
    s->tim1_dir=(dir & TIM_CR1_DIR)!=0U;
    s->timer_span=DWT->CYCCNT-s->dwt;
    FOC_PRE_CAPTURE_TEST_POINT(2);
    s->cycles[0]=s->count[0]=0U;
#define FOC_PRE_READ(i) s->cycles[i]=foc_preempt_irq[i].cycles; \
    FOC_PRE_CAPTURE_TEST_POINT(2+(i)*2); \
    s->count[i]=foc_preempt_irq[i].count; FOC_PRE_CAPTURE_TEST_POINT(3+(i)*2)
    FOC_PRE_READ(1); FOC_PRE_READ(2); FOC_PRE_READ(3);
#undef FOC_PRE_READ
    s->errors=foc_preempt_irq[1].invalid+foc_preempt_irq[2].invalid+foc_preempt_irq[3].invalid;
    s->valid=1U;
}
FOC_RAM_PATH static void Stamp(FocPreStamp *s)
{
    stamp_requested=1U;
    __DMB();
    Capture(s);
    __DMB();
    if (!stamp_requested) {
        *s=assisted_stamp;
        ++foc_stamp_assisted_count;
    }
    stamp_requested=0U;
}
#else
static inline uint32_t Calls(void)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    return foc_preempt_irq[1].count+foc_preempt_irq[2].count+foc_preempt_irq[3].count;
#else
    return foc_preempt_irq[0].count+foc_preempt_irq[1].count+
           foc_preempt_irq[2].count+foc_preempt_irq[3].count;
#endif
}
FOC_RAM_PATH static void Stamp(FocPreStamp *s)
{
    uint32_t before=Calls();
    __DMB();
    s->dwt=DWT->CYCCNT;
    s->tim1_cnt=TIM1->CNT;
    s->tim1_dir=(TIM1->CR1 & TIM_CR1_DIR)!=0U;
    s->timer_span=DWT->CYCCNT-s->dwt;
#define FOC_PRE_READ(i) s->cycles[i]=foc_preempt_irq[i].cycles; \
    s->count[i]=foc_preempt_irq[i].count
    FOC_PRE_READ(0); FOC_PRE_READ(1); FOC_PRE_READ(2); FOC_PRE_READ(3);
#undef FOC_PRE_READ
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    /* TIM7 priority 3 cannot preempt ADC priority 2. It may be suspended
     * underneath this ADC; never read its half-published totals as preempt. */
    s->cycles[0]=s->count[0]=0U;
    s->errors=foc_preempt_irq[1].invalid+foc_preempt_irq[2].invalid+foc_preempt_irq[3].invalid;
#else
    s->errors=foc_preempt_irq[0].invalid+foc_preempt_irq[1].invalid+
              foc_preempt_irq[2].invalid+foc_preempt_irq[3].invalid;
#endif
    __DMB();
    s->valid=(uint32_t)(before==Calls());
}
#endif
#endif
FOC_RAM_PATH FocPreToken FocPreempt_IrqBegin(unsigned source)
{
#if !FOC_HEAVY_PROFILE_ENABLE
    (void)source;
    FocPreToken t={0U,0U,0U}; return t;
#else
#if defined(AS5047P_DMA_FOC_FIRST)
    (void)source;
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE) && !defined(AS5047P_DMA_FOC_FIRST)
    if (source!=FOC_PRE_GUARD && stamp_requested) {
        Capture(&assisted_stamp);
        __DMB();
        stamp_requested=0U;
    }
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    FocPreToken t={DWT->CYCCNT,0U,1U};
    return t;
#else
    uint32_t before=foc_preempt_irq[0].count;
    __DMB();
    FocPreToken t;
    t.dwt=DWT->CYCCNT;
    t.guard_cycles=foc_preempt_irq[0].cycles;
    __DMB();
    t.valid=(uint32_t)(source==0U || before==foc_preempt_irq[0].count);
    return t;
#endif
#endif
}
FOC_RAM_PATH void FocPreempt_IrqEnd(unsigned source,FocPreToken t)
{
#if !FOC_HEAVY_PROFILE_ENABLE
    (void)source; (void)t;
#else
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    uint32_t inclusive=DWT->CYCCNT-t.dwt;
    /* Equal-priority encoder IRQs do not nest. TIM7's service wall time may
     * contain ADC/encoder children and is NOT used in ADC attribution. */
    foc_preempt_irq[source].cycles+=inclusive;
#else
    uint32_t before=foc_preempt_irq[0].count;
    __DMB();
    uint32_t now=DWT->CYCCNT;
    uint32_t children=source==0U ? 0U : foc_preempt_irq[0].cycles-t.guard_cycles;
    __DMB();
    uint32_t inclusive=now-t.dwt;
    if (!t.valid || (source!=0U && before!=foc_preempt_irq[0].count) || children>inclusive)
        ++foc_preempt_irq[source].invalid;
    else foc_preempt_irq[source].cycles+=inclusive-children;
#endif
    if (inclusive>foc_preempt_irq[source].max_single)
        foc_preempt_irq[source].max_single=inclusive;
    __DMB();
    ++foc_preempt_irq[source].count;
#endif
}
FOC_RAM_PATH uint32_t FocPreempt_Begin(void)
{
#if FOC_HEAVY_PROFILE_ENABLE
    Stamp(&entry);
    return entry.dwt;
#else
    return DWT->CYCCNT;
#endif
}
/* Volatile scalar stores intentionally avoid a compiler-generated memcpy.
 * Only ADC writes these frozen frames. Foreground detects in-flight ADC by
 * the monotonic frames publication counter (and a second check). */
#if FOC_HEAVY_PROFILE_ENABLE
FOC_RAM_PATH __attribute__((noinline))
static void Save(volatile FocPreFrame *out,const FocPreFrame *f)
{
    out->wall=f->wall; out->preempt=f->preempt; out->active_est=f->active_est;
#define FOC_PRE_SAVE(i) out->cycles[i]=f->cycles[i]; out->count[i]=f->count[i]
    FOC_PRE_SAVE(0); FOC_PRE_SAVE(1); FOC_PRE_SAVE(2); FOC_PRE_SAVE(3);
#undef FOC_PRE_SAVE
    out->dominant=f->dominant; out->path=f->path;
    __DMB(); out->valid=f->valid;
}
FOC_RAM_PATH static void SaveDeadline(const FocPreFrame *f)
{
    if (deadline_snapshot.captured) return;
    deadline_snapshot.wall_cycles=f->wall;
    deadline_snapshot.active_est_cycles=f->active_est;
    deadline_snapshot.tim2_cycles=f->cycles[1];
    deadline_snapshot.tim2_count=f->count[1];
    deadline_snapshot.dma_rx_cycles=f->cycles[2];
    deadline_snapshot.dma_rx_count=f->count[2];
    deadline_snapshot.other_irq_cycles=f->cycles[0]+f->cycles[3];
    deadline_snapshot.other_irq_count=f->count[0]+f->count[3];
    deadline_snapshot.preempt_total_cycles=f->preempt;
    deadline_snapshot.tim1_cnt=exit_stamp.tim1_cnt;
    deadline_snapshot.tim1_dir=exit_stamp.tim1_dir;
    deadline_snapshot.dwt_entry=entry.dwt;
    deadline_snapshot.dwt_exit=exit_stamp.dwt;
    deadline_snapshot.timer_span=exit_stamp.timer_span;
    deadline_snapshot.captured=1U;
    __DMB(); deadline_snapshot.valid=f->valid; /* final publication store */
}
#endif
FOC_RAM_PATH uint32_t FocPreempt_End(uint32_t start,uint32_t path)
{
#if FOC_HEAVY_PROFILE_ENABLE
    Stamp(&exit_stamp);
    FocPre_Delta(&frame,&entry,&exit_stamp);
    frame.path=path; /* Existing discriminator path, diagnostic label only. */
    frame.valid=(uint32_t)(frame.valid && foc_probe_priorities_ok && start==entry.dwt);
    /* This is the exact SAME wall boundary returned to the existing outer
     * 8500-cycle protection recorder, not a second independently timed max. */
    uint32_t wall=exit_stamp.dwt-start;
    if (wall>foc_preempt_timing.wall_max) foc_preempt_timing.wall_max=wall;
    if (!frame.valid || !foc_probe_priorities_ok) ++foc_preempt_timing.invalid;
    else {
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
        if (frame.cycles[0]>foc_tim7_preempt_max_cycles)
            foc_tim7_preempt_max_cycles=frame.cycles[0];
#endif
        if (frame.preempt>foc_preempt_timing.preempt_max) {
            foc_preempt_timing.preempt_max=frame.preempt;
            Save(&foc_preempt_timing.worst_preempt,&frame);
        }
        if (frame.active_est>foc_preempt_timing.active_est_max)
            foc_preempt_timing.active_est_max=frame.active_est;
    }
    if (wall>8499U) {
        if (!foc_preempt_timing.deadline_miss) {
            Save(&foc_preempt_timing.first_miss,&frame);
        }
        SaveDeadline(&frame); /* reset/manual clear of new ledger is independent */
        ++foc_preempt_timing.deadline_miss;
    }
    uint32_t tail=DWT->CYCCNT-exit_stamp.dwt;
    if (tail>foc_preempt_timing.observer_tail_max) foc_preempt_timing.observer_tail_max=tail;
    __DMB();
    ++foc_preempt_timing.frames;
    return wall;
#else
    (void)path;
    uint32_t wall=DWT->CYCCNT-start;
    if (wall>foc_preempt_timing.wall_max) foc_preempt_timing.wall_max=wall;
    if (wall>8499U) ++foc_preempt_timing.deadline_miss;
    return wall;
#endif
}
void FocPreempt_CheckPriorities(void)
{
    const IRQn_Type ids[7]={TIM7_DAC_IRQn,TIM2_IRQn,DMA1_Channel4_IRQn,
        DMA1_Channel5_IRQn,ADC1_2_IRQn,SysTick_IRQn,PendSV_IRQn};
    for (unsigned i=0U;i<7U;++i) foc_probe_irq_priority[i]=NVIC_GetPriority(ids[i]);
    uint32_t ok=(uint32_t)(NVIC_GetPriorityGrouping()==3U &&
        foc_probe_irq_priority[0]==FOC_SOFTWARE_GUARD_PRIORITY &&
#if defined(AS5047P_DMA_FOC_FIRST)
        foc_probe_irq_priority[1]==3U && foc_probe_irq_priority[2]==3U &&
        foc_probe_irq_priority[3]==3U && NVIC_GetPriority(TIM6_DAC_IRQn)==4U &&
#else
        foc_probe_irq_priority[1]==1U && foc_probe_irq_priority[2]==1U && foc_probe_irq_priority[3]==1U &&
#endif
        foc_probe_irq_priority[4]==2U && foc_probe_irq_priority[5]>=2U &&
        foc_probe_irq_priority[6]>=2U);
    uint32_t unexpected=0U;
    /* All external vectors implemented by this STM32G474 device header.
     * No invented SysTick/CAN/UART contributors and no priority changes. */
    for (int n=0;n<=(int)FMAC_IRQn;++n) {
        IRQn_Type id=(IRQn_Type)n;
        if (NVIC_GetEnableIRQ(id) && NVIC_GetPriority(id)<2U &&
#if !defined(AS5047P_DMA_FOC_FIRST)
            id!=TIM7_DAC_IRQn && id!=TIM2_IRQn &&
            id!=DMA1_Channel4_IRQn && id!=DMA1_Channel5_IRQn) {
#else
            1) { /* No known higher-priority external service in this profile. */
#endif
            ok=0U; unexpected=(uint32_t)n+1U;
        }
    }
    foc_probe_unexpected_irq=unexpected;
    __DMB();
    foc_probe_priorities_ok=ok;
}

/* UART enqueue only at the existing low-rate MonitorTask call site. Reading
 * volatile counters does not mask or delay ADC/guardian. If ADC interrupts
 * the copy, skip this print; next foreground period may try again. */
extern FocPwmWriteProbe foc_pwm_write_profile,foc_pwm_duty_profile;
extern uint32_t foc_ccr_probe_blocked,foc_ccr_probe_hard_late;
extern int32_t foc_ccr_probe_latch_margin_min;
extern uint32_t foc_ccr_probe_latch_late;
extern uint32_t foc_ccr_probe_post_unsafe;
static void PrintValue(const char *section,const char *key,int32_t value,uint8_t time)
{
    if (time) {
        uint32_t mag=(uint32_t)(value<0 ? -value : value);
        UART_Async_Printf(160U,0U,"%s %s=%s%lu.%03lu\r\n",section,key,
            value<0 ? "-" : "",(unsigned long)(mag/170U),
            (unsigned long)((mag%170U)*1000U/170U));
    } else UART_Async_Printf(160U,0U,"%s %s=%lu\r\n",section,key,(unsigned long)(uint32_t)value);
}
void FocPreempt_Monitor(void)
{
#if !FOC_HEAVY_PROFILE_ENABLE
    PrintValue("FOC TIMING","wall_max_us",(int32_t)foc_preempt_timing.wall_max,1U);
    PrintValue("FOC TIMING","deadline_miss",(int32_t)foc_preempt_timing.deadline_miss,0U);
    PrintValue("PWM COMMIT","actual_late_commit_count",(int32_t)foc_ccr_probe_hard_late,0U);
    PrintValue("PWM COMMIT","actual_margin_min_us",foc_pwm_write_profile.pwm_update_margin_ticks_min,1U);
#else
    uint32_t seq=foc_preempt_timing.frames;
    __DMB();
    FocPreTiming t=foc_preempt_timing;
    FocPwmWriteProbe actual=foc_pwm_write_profile,hyp=foc_pwm_duty_profile;
    __DMB();
    if (seq!=foc_preempt_timing.frames) return;
    PrintValue("FOC TIMING","wall_max_us",(int32_t)t.wall_max,1U);
    PrintValue("FOC TIMING","preempt_max_us",(int32_t)t.preempt_max,1U);
    PrintValue("FOC TIMING","active_est_max_us",(int32_t)t.active_est_max,1U);
    PrintValue("FOC TIMING","deadline_miss",(int32_t)t.deadline_miss,0U);
    PrintValue("FOC TIMING","invalid",(int32_t)t.invalid,0U);
    PrintValue("FOC TIMING","observer_tail_max_us",(int32_t)t.observer_tail_max,1U);
    PrintValue("FOC TIMING","assisted_stamps",(int32_t)foc_stamp_assisted_count,0U);
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    extern uint32_t foc_pending_commit_max_cycles, foc_pending_generation_max_cycles;
    PrintValue("PIPELINE","commit_max_cycles",(int32_t)foc_pending_commit_max_cycles,0U);
    PrintValue("PIPELINE","generation_max_cycles",(int32_t)foc_pending_generation_max_cycles,0U);
    PrintValue("FOC TIMING","tim7_preempt_max_us",(int32_t)foc_tim7_preempt_max_cycles,1U);
#endif
    static const char *const names[4]={"TIM7","TIM2","DMA1_CH4","DMA1_CH5"};
    for (unsigned i=0U;i<4U;++i) {
        uint32_t count=foc_preempt_irq[i].count;
        FocPreIrq irq=foc_preempt_irq[i];
        __DMB();
        if (count!=foc_preempt_irq[i].count) continue;
        UART_Async_Printf(160U,0U,"IRQ %s %s count=%lu cycles_total=%lu invalid=%lu\r\n",
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
#if defined(AS5047P_DMA_FOC_FIRST)
            "SERVICE_WALL_INCLUDING_CHILDREN",
#else
            i==0U ? "SERVICE_WALL_INCLUDING_CHILDREN" : "PREEMPT",
#endif
#else
            "PREEMPT",
#endif
            names[i],(unsigned long)irq.count,(unsigned long)irq.cycles,(unsigned long)irq.invalid);
        PrintValue(names[i],"max_single_us",(int32_t)irq.max_single,1U);
    }
    PrintValue("PWM COMMIT","actual_commit_count",(int32_t)actual.writes,0U);
    PrintValue("PWM COMMIT","actual_margin_min_us",actual.pwm_update_margin_ticks_min,1U);
    PrintValue("PWM COMMIT",
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
        "actual_late_commit_count",
#else
        "actual_late_count",
#endif
        (int32_t)foc_ccr_probe_hard_late,0U);
    /* Detailed commit proof remains in its immutable/image-bound SRAM decoder;
     * do not spend scarce A-slot Flash on duplicate UART fields. */
    PrintValue("HYPOTHETICAL PWM","hyp_margin_min_us",hyp.pwm_update_margin_ticks_min,1U);
    PrintValue("PRIORITY","ok",(int32_t)foc_probe_priorities_ok,0U);
    PrintValue("PRIORITY","unexpected",(int32_t)foc_probe_unexpected_irq,0U);
    if (t.deadline_miss) {
        const FocPreFrame *f=&t.first_miss;
        PrintValue("FOC MISS","wall_us",(int32_t)f->wall,1U);
        PrintValue("FOC MISS","preempt_us",(int32_t)f->preempt,1U);
        PrintValue("FOC MISS","active_est_us",(int32_t)f->active_est,1U);
        PrintValue("FOC MISS","valid",(int32_t)f->valid,0U);
        PrintValue("FOC MISS","dominant",(int32_t)f->dominant,0U);
        PrintValue("FOC MISS","path",(int32_t)f->path,0U);
        for (unsigned i=0U;i<4U;++i) {
            UART_Async_Printf(160U,0U,"FOC MISS IRQ %s cycles=%lu count=%lu\r\n",names[i],
                (unsigned long)f->cycles[i],(unsigned long)f->count[i]);
        }
        /* Immutable until reset. All formatting remains task-only. */
        if (deadline_snapshot.captured) {
            __DMB();
            const volatile FocDeadlineSnapshot *d=&deadline_snapshot;
            UART_Async_Printf(180U,0U,
                "DEADLINE valid=%lu CNT=%lu DIR=%lu DWT=%lu:%lu SPAN=%lu\r\n",
                (unsigned long)d->valid,
                (unsigned long)d->tim1_cnt,(unsigned long)d->tim1_dir,
                (unsigned long)d->dwt_entry,(unsigned long)d->dwt_exit,
                (unsigned long)d->timer_span);
        }
    }
#endif
}
