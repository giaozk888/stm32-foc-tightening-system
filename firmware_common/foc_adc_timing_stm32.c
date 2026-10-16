#include "main.h"
#include "foc_adc_timing_stm32.h"
#include "foc_adc_raw_buffer.h"
#include "foc_adc_clock_stm32.h"
#include "foc_hot_path.h"
#if defined(FOC_PWM_BOUNDARY_TRACE)
#include "foc_pwm_boundary.h"
#include "foc_irq_load.h"
static FocPwmBoundary boundary;
static FocPwmBoundaryFrame boundary_frame;
static uint32_t boundary_irq_start;
#endif
#if defined(FOC_PWM_BOUNDARY_LITE)
#include "foc_pwm_boundary_lite.h"
static FocPwmBoundaryLite boundary_lite;
static uint8_t boundary_lite_entry_stable;
#endif
#include <string.h>
#include <stdio.h>

static const FocWindowConfig config = {
    FOC_ADC_TIMER_ARR, 85U, FOC_ADC_SETTLE_TICKS,
    FOC_ADC_TRIGGER_LATENCY_MAX_TICKS, 50U,
    (FocSenseTopology)FOC_ADC_SENSE_TOPOLOGY,
    FOC_ADC_MIN_LOW_ON_TICKS, FOC_ADC_SAMPLE_PLACEMENT
};
static FocAdcTimingSnapshot stats;
/* Static zero initialization is FREE/empty for this queue; no runtime reset
 * is allowed while the ADC ISR or its single consumer is running. */
static FocRawBuffer raw_buffers;
static uint8_t worker_busy;
static uint32_t irq_remaining_ticks;
#if defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
static uint32_t irq_begin_cycles;
static uint8_t irq_commit_active;
#endif
static uint8_t have_plan;
static uint8_t clock_certified;
typedef struct { uint32_t cr, cfgr, pll, trim; } ClockProof;
static ClockProof clock_proof;
FOC_RAM_PATH static ClockProof ClockRead(void)
{
    ClockProof p = {RCC->CR, RCC->CFGR, RCC->PLLCFGR, RCC->ICSCR};
    return p;
}
FOC_RAM_PATH static int ClockEqual(ClockProof a, ClockProof b)
{
    return a.cr == b.cr && a.cfgr == b.cfgr && a.pll == b.pll && a.trim == b.trim;
}

FOC_RAM_PATH FocWindowStatus FocAdcTiming_Prepare(float u, float v, float w, FocWindowPlan *plan)
{
    return FocAdcWindow_Duty(&config, u, v, w, plan);
}
void FocAdcTiming_PlanFailed(FocWindowStatus status)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    stats.last_plan_status = (uint8_t)status;
    have_plan = 0U;
    ++stats.plan_failures;
    __set_PRIMASK(mask);
}

FocWindowStatus FocAdcTiming_Commit(float u, float v, float w)
{
    FocWindowPlan plan;
    FocWindowStatus result = FocAdcTiming_Prepare(u, v, w, &plan);
    if (result != FOC_WINDOW_OK) {
        FocAdcTiming_PlanFailed(result);
        return result;
    }
    FocAdcTiming_CommitPrepared(&plan);
    return result;
}
FOC_RAM_PATH void FocAdcTiming_CommitPrepared(const FocWindowPlan *prepared)
{
    const FocWindowPlan plan = *prepared;
    /* All four CCRs are preloaded by HAL PWM channel configuration. Block
     * UEV transfer for this short write group, not merely CPU preemption.
     * Do not force UG while running: it can move sampling/PWM mid-period.
     * Preserve an existing UDIS and the caller's interrupt mask. */
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    uint32_t udis = TIM1->CR1 & TIM_CR1_UDIS;
    TIM1->CR1 |= TIM_CR1_UDIS;
    TIM1->CCR1 = plan.phase[0];
    TIM1->CCR2 = plan.phase[1];
    TIM1->CCR3 = plan.phase[2];
    TIM1->CCR4 = plan.trigger;
    __DMB();
    if (udis == 0U) TIM1->CR1 &= ~TIM_CR1_UDIS;
    /* At standstill load the shadow registers before CH4/CEN is started.
     * OC4REF remains low at CNT=0 for PWM2 with CCR4>0. */
    if ((TIM1->CR1 & TIM_CR1_CEN) == 0U && udis == 0U) {
        TIM1->CNT = 0U;
        TIM1->EGR = TIM_EGR_UG;
    }
    stats.trigger = plan.trigger;
    stats.last_plan_status = FOC_WINDOW_OK;
    stats.slack_ticks = plan.slack_ticks;
    ++stats.plan_sequence;
    have_plan = 1U;
    __set_PRIMASK(mask);
}
FOC_RAM_PATH int FocAdcTiming_RcActuationReady(void)
{
#if defined(FOC_PWM_BOUNDARY_TRACE) || defined(FOC_PWM_BOUNDARY_LITE)
    /* Even the lightweight observer changes execution time. Never admit
     * motor motion from either evidence-only build. */
    return 0;
#elif defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
    /* Caller serializes with ADC/guardian. These are observed counters, not a
     * WCET proof; a nonzero coarse alarm must not silently admit actuation. */
    return have_plan && stats.pairs >= 1000U && stats.dwt_on && stats.max_cycles &&
        !stats.pair_misses && !stats.plan_failures && !stats.deadline_misses &&
        !stats.commit_failures;
#else
    return 0; /* Never turn a hard-off/legacy profile into an RC candidate. */
#endif
}
FOC_RAM_PATH int FocAdcTiming_CommitBeforeBottom(const FocWindowPlan *prepared)
{
#if defined(FOC_PWM_BOUNDARY_TRACE) || defined(FOC_PWM_BOUNDARY_LITE)
    (void)prepared;
    return 0; /* No duty publication in the observer-only RC build. */
#elif defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    ++stats.commit_checks;
    uint32_t cr1 = TIM1->CR1;
    uint32_t elapsed = DWT->CYCCNT - irq_begin_cycles;
    uint32_t count = TIM1->CNT;
    int allowed = prepared != NULL && irq_commit_active && __get_IPSR() != 0U &&
        !stats.commit_failures && !stats.deadline_misses &&
        (DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) &&
        (cr1 & (TIM_CR1_CEN | TIM_CR1_UDIS | TIM_CR1_DIR)) == (TIM_CR1_CEN | TIM_CR1_DIR) &&
        (TIM1->CR1 & TIM_CR1_DIR) && count > FOC_ADC_COMMIT_GUARD_TICKS &&
        irq_remaining_ticks > FOC_ADC_COMMIT_GUARD_TICKS &&
        elapsed < irq_remaining_ticks - FOC_ADC_COMMIT_GUARD_TICKS;
    if (!allowed) {
        ++stats.commit_failures;
        __set_PRIMASK(mask);
        return 0;
    }
    FocAdcTiming_CommitPrepared(prepared);
    __set_PRIMASK(mask);
    return 1;
#else
    (void)prepared;
    return 0;
#endif
}
FOC_RAM_PATH static int TimerGeometryReady(void)
{
    /* Reject a clock/register configuration that invalidates tick geometry.
     * This is a digital check, not proof of sense polarity or analog settling. */
    return FOC_ADC_SENSE_TOPOLOGY != 0 && have_plan != 0U &&
        TIM1->ARR == FOC_ADC_TIMER_ARR && TIM1->PSC == 0U && TIM1->RCR == 0U &&
        (TIM1->CR1 & (TIM_CR1_CMS | TIM_CR1_CKD | TIM_CR1_UDIS)) == TIM_COUNTERMODE_CENTERALIGNED1 &&
        (TIM1->BDTR & TIM_BDTR_DTG) == config.dead_ticks &&
        (TIM1->CCMR1 & (TIM_CCMR1_OC1PE | TIM_CCMR1_OC2PE)) == (TIM_CCMR1_OC1PE | TIM_CCMR1_OC2PE) &&
        (TIM1->CCMR2 & (TIM_CCMR2_OC3PE | TIM_CCMR2_OC4PE)) == (TIM_CCMR2_OC3PE | TIM_CCMR2_OC4PE) &&
        (TIM1->CR2 & TIM_CR2_MMS2) == TIM_TRGO2_OC4REF;
}
int FocAdcTiming_CanStart(void)
{
    return TimerGeometryReady() && HAL_RCC_GetHCLKFreq() == 170000000U &&
        HAL_RCC_GetPCLK2Freq() == 170000000U && FocAdcClock_IsExpected();
}
int FocAdcTiming_CertifyClock(void)
{
    /* No clock writes occur in the interrupt path. Reject a changed snapshot
     * during foreground validation, and never certify from a masked ISR. */
    clock_certified = 0U;
    if (__get_IPSR() != 0U || __get_PRIMASK() != 0U) return 0;
    ClockProof before = ClockRead();
    if (!FocAdcTiming_CanStart()) return 0;
    ClockProof after = ClockRead();
    if (!ClockEqual(before, after)) return 0;
    clock_proof = after;
    __DMB();
    clock_certified = 1U;
    return 1;
}
FOC_RAM_PATH int FocAdcTiming_FastCanStart(void)
{
#if defined(FOC_IRQ_COMPACT)
    /* Identical live clock checks without aggregate return/argument copies.
     * Do not cache these across guardian ticks or skip configuration checks. */
    return clock_certified && clock_proof.cr == RCC->CR &&
        clock_proof.cfgr == RCC->CFGR && clock_proof.pll == RCC->PLLCFGR &&
        clock_proof.trim == RCC->ICSCR &&
        __HAL_RCC_GET_ADC12_SOURCE() == FOC_ADC_CLOCK_SOURCE &&
        (ADC12_COMMON->CCR & (ADC_CCR_CKMODE | ADC_CCR_PRESC)) == FOC_ADC_CLOCK_PRESCALER &&
        TimerGeometryReady();
#else
    return clock_certified && ClockEqual(clock_proof, ClockRead()) &&
        __HAL_RCC_GET_ADC12_SOURCE() == FOC_ADC_CLOCK_SOURCE &&
        (ADC12_COMMON->CCR & (ADC_CCR_CKMODE | ADC_CCR_PRESC)) == FOC_ADC_CLOCK_PRESCALER &&
        TimerGeometryReady();
#endif
}
FOC_RAM_PATH int FocAdcTiming_PairReady(void)
{
    /* No ISR polling or reuse of ADC2's preceding conversion. */
    int ready = (ADC1->ISR & ADC_ISR_JEOS) != 0U &&
                (ADC2->ISR & ADC_ISR_JEOS) != 0U;
    if (!ready) ++stats.pair_misses;
    return ready;
}
FOC_RAM_PATH void FocAdcTiming_RecordRaw(uint16_t u, uint16_t v)
{
    /* CCR reads expose preloads, not guaranteed active shadows. These are
     * command-register values at sample handling; do not label physical edges. */
    ++stats.pairs;
    FocRawBuffer_Push(&raw_buffers, u, v, (uint16_t)TIM1->CCR1,
                     (uint16_t)TIM1->CCR2, (uint16_t)TIM1->CCR3,
                     (uint16_t)TIM1->CCR4, stats.plan_sequence);
}
int FocAdcTiming_ProcessRawOne(void)
{
    if (__get_IPSR() != 0U || __get_PRIMASK() != 0U) return 0;
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    if (worker_busy != 0U) {
        __set_PRIMASK(mask);
        return 0;
    }
    worker_busy = 1U;
    __set_PRIMASK(mask);
    FocRawBlockView view;
    if (!FocRawBuffer_Acquire(&raw_buffers, &view)) {
        mask = __get_PRIMASK(); __disable_irq();
        worker_busy = 0U; __set_PRIMASK(mask);
        return 0;
    }
    /* Only a background owner computes statistics. The ADC ISR may preempt
     * this loop and fill the other block, but cannot modify this READING block. */
    uint32_t start = DWT->CYCCNT;
    FocRawSpread result;
    FocRawSpread_Reset(&result);
    for (unsigned i = 0; i < FOC_SPREAD_BLOCK; ++i)
        FocRawSpread_Push(&result, view.block->sample[i][0], view.block->sample[i][1]);
    uint32_t elapsed = DWT->CYCCNT - start;
    /* Bounded result publication only, not the 256-sample computation loop.
     * Keep the existing snapshot interface coherent with ProtocolTask readers. */
    mask = __get_PRIMASK(); __disable_irq();
    stats.raw = result;
    stats.command_phase[0] = view.block->command_phase[0];
    stats.command_phase[1] = view.block->command_phase[1];
    stats.command_phase[2] = view.block->command_phase[2];
    stats.command_trigger = view.block->command_trigger;
    stats.block_plan_sequence = view.block->plan_sequence;
    stats.mixed_block = view.block->mixed;
    stats.blocks = view.block->sequence; /* Capture ID; drops leave visible holes. */
    ++stats.processed_blocks;
    if ((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) != 0U) {
        stats.worker_last_cycles = elapsed;
        if (elapsed > stats.worker_max_cycles) stats.worker_max_cycles = elapsed;
    }
    __set_PRIMASK(mask);
    FocRawBuffer_Release(&raw_buffers, &view);
    mask = __get_PRIMASK(); __disable_irq();
    worker_busy = 0U; __set_PRIMASK(mask);
    return 1;
}
void FocAdcTiming_NoteWorkerStack(uint32_t free_bytes)
{
    /* Single foreground worker writes this diagnostic; never gates control. */
    stats.worker_stack_free_bytes = free_bytes;
    stats.worker_stack_valid = 1U;
}
FOC_RAM_PATH uint32_t FocAdcTiming_IrqEnter(void)
{
#if defined(FOC_PWM_BOUNDARY_TRACE)
    uint32_t trace_mask=__get_PRIMASK(); __disable_irq();
    FocIrqSource_FrameBegin();
    boundary_irq_start=FocIrqLoad_Read();
#endif
#if defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
    /* Start before timer reads: elapsed includes the counter snapshot cost. */
    irq_begin_cycles = DWT->CYCCNT;
    irq_commit_active = 1U;
#endif
    ++stats.irq_entries;
    stats.dwt_on = (uint8_t)((DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk) != 0U);
    /* CCR4 reads the preload rather than the active sampling compare. Use
     * the live counter/direction for a coarse remaining-time alarm instead. */
    uint32_t direction_before = TIM1->CR1 & TIM_CR1_DIR;
    uint32_t count = TIM1->CNT;
    uint32_t direction_after = TIM1->CR1 & TIM_CR1_DIR;
    irq_remaining_ticks = direction_before != direction_after ? count :
        (direction_after != 0U ? count : 2U * FOC_ADC_TIMER_ARR - count);
#if defined(FOC_PWM_BOUNDARY_LITE)
    boundary_lite_entry_stable=(uint8_t)(direction_before==direction_after &&
        count<=FOC_ADC_TIMER_ARR && clock_certified);
#endif
#if defined(FOC_PWM_BOUNDARY_TRACE)
    boundary_frame.seq=stats.irq_entries;
    boundary_frame.entry_count=count;
    boundary_frame.entry_down=(uint8_t)(direction_after != 0U);
    boundary_frame.stable=(uint8_t)(direction_before == direction_after && count <= FOC_ADC_TIMER_ARR);
    boundary_frame.remaining=irq_remaining_ticks;
    boundary_frame.geometry=(uint8_t)FocAdcTiming_FastCanStart();
    boundary_frame.dwt=stats.dwt_on;
    __set_PRIMASK(trace_mask);
    return irq_begin_cycles; /* Include timer/config snapshot cost in this probe. */
#else
    return DWT->CYCCNT;
#endif
}
FOC_RAM_PATH void FocAdcTiming_IrqExit(uint32_t start)
{
#if defined(FOC_PWM_BOUNDARY_TRACE)
    uint32_t trace_mask=__get_PRIMASK(); __disable_irq();
    /* A single boundary for wall, union and source attribution. Source hooks
     * cannot be active at ADC priority here. Freeze copies/formatting are not
     * part of the reported work interval; they still cost diagnostic time. */
    boundary_frame.geometry=(uint8_t)(boundary_frame.geometry && FocAdcTiming_FastCanStart());
    boundary_frame.dwt=(uint8_t)(boundary_frame.dwt && (DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk));
    uint32_t exit_direction=TIM1->CR1 & TIM_CR1_DIR;
    boundary_frame.exit_count=TIM1->CNT;
    boundary_frame.exit_down=(uint8_t)((TIM1->CR1 & TIM_CR1_DIR) != 0U);
    boundary_frame.stable=(uint8_t)(boundary_frame.stable &&
        boundary_frame.exit_down==(exit_direction != 0U) && boundary_frame.exit_count<=FOC_ADC_TIMER_ARR);
    uint32_t trace_end=DWT->CYCCNT;
    boundary_frame.wall=trace_end-start;
    boundary_frame.irq=FocIrqLoad_Read()-boundary_irq_start;
    FocIrqSource_FrameEnd(&boundary_frame.sources);
    FocPwmBoundary_Record(&boundary,&boundary_frame);
#endif
#if defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
    irq_commit_active = 0U;
#endif
    if (stats.dwt_on == 0U) {
#if defined(FOC_PWM_BOUNDARY_TRACE)
        __set_PRIMASK(trace_mask);
#endif
        return;
    }
#if defined(FOC_PWM_BOUNDARY_TRACE)
    uint32_t cycles=boundary_frame.wall;
#else
    uint32_t cycles = DWT->CYCCNT - start;
#endif
    stats.last_cycles = cycles;
    if (cycles > stats.max_cycles) stats.max_cycles = cycles;
    /* Only a conservative gross-overrun alarm (IRQ entry->exit vs remaining
     * timer ticks). Does not include trigger/ADC/IRQ-entry latency or prove WCET. */
    if (cycles >= irq_remaining_ticks) {
        ++stats.deadline_misses;
#if defined(FOC_PWM_BOUNDARY_LITE)
        if (stats.dwt_on)
            FocPwmBoundaryLite_Record(&boundary_lite,stats.irq_entries,
                irq_remaining_ticks,cycles,boundary_lite_entry_stable);
#endif
    }
#if defined(FOC_PWM_BOUNDARY_TRACE)
    __set_PRIMASK(trace_mask);
#endif
}
void FocAdcTiming_Snapshot(FocAdcTimingSnapshot *out)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    *out = stats;
    FocRawBufferInfo info;
    FocRawBuffer_Info(&raw_buffers, &info);
    out->dropped_blocks = info.dropped_blocks;
    out->dropped_samples = info.dropped_samples;
    out->rejected_samples = info.rejected_samples;
    out->buffers_ready = (uint8_t)info.ready;
    out->buffers_reading = (uint8_t)info.reading;
    out->worker_busy = worker_busy;
    __set_PRIMASK(mask);
}

/* Foreground only. Keep formatting/snapshot stack out of the 20kHz ISR. */
__attribute__((noinline))
int FocAdcTiming_Format(const char *command, char *out, uint32_t size)
{
#if defined(FOC_PWM_BOUNDARY_LITE)
    if (!strncmp(command,"ADC BOUNDARY LITE",17U)) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        FocPwmBoundaryLiteFrame first=boundary_lite.first;
        FocPwmBoundaryLiteFrame worst=boundary_lite.worst;
        uint32_t pairs=stats.pairs, late=stats.deadline_misses;
        __set_PRIMASK(mask);
        int n=-1;
        if (!strcmp(command,"ADC BOUNDARY LITE"))
            n=snprintf(out,size,"OK ADC BOUNDARY LITE TRACE=1 PAIRS=%lu LATE=%lu FIRST=%u WORST=%u RCR=%lu HW_VERIFIED=0",
                (unsigned long)pairs,(unsigned long)late,first.valid,worst.valid,
                (unsigned long)TIM1->RCR);
        else if (!strcmp(command,"ADC BOUNDARY LITE FIRST") ||
                 !strcmp(command,"ADC BOUNDARY LITE WORST")) {
            FocPwmBoundaryLiteFrame f=strstr(command," FIRST") ? first : worst;
            n=snprintf(out,size,"OK ADC BOUNDARY LITE FRAME VALID=%u SEQ=%lu REM=%lu WALL=%lu OVER=%lu HW_VERIFIED=0",
                f.valid,(unsigned long)f.seq,(unsigned long)f.remaining,
                (unsigned long)f.wall,(unsigned long)(f.valid ? f.wall-f.remaining : 0U));
        }
        return n>=0 && (uint32_t)n<size;
    }
#endif
#if defined(FOC_PWM_BOUNDARY_TRACE)
    if (!strncmp(command,"ADC BOUNDARY",12U)) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint32_t frames=boundary.frames, invalid=boundary.invalid, late=boundary.late;
        FocPwmBoundaryFrame f=strstr(command," FIRST") ? boundary.first_late : boundary.worst;
        __set_PRIMASK(mask);
        int n=-1;
        if (!strcmp(command,"ADC BOUNDARY"))
            n=snprintf(out,size,"OK ADC BOUNDARY TRACE=1 FRAMES=%lu INVALID=%lu LATE=%lu WORST_VALID=%u MARGIN_TICKS=%ld RCR=%lu HW_VERIFIED=0",
                (unsigned long)frames,(unsigned long)invalid,(unsigned long)late,f.valid,
                (long)f.margin,(unsigned long)TIM1->RCR);
        else if (!strcmp(command,"ADC BOUNDARY FIRST IRQ") || !strcmp(command,"ADC BOUNDARY WORST IRQ"))
            n=snprintf(out,size,"OK ADC BOUNDARY IRQ VALID=%u SEQ=%lu ORDER=G,T,R,X BODY=EXCL ERR=%lu CYC=%lu,%lu,%lu,%lu CNT=%lu,%lu,%lu,%lu",
                f.valid,(unsigned long)f.seq,(unsigned long)f.sources.error,
                (unsigned long)f.sources.cycles[0],(unsigned long)f.sources.cycles[1],
                (unsigned long)f.sources.cycles[2],(unsigned long)f.sources.cycles[3],
                (unsigned long)f.sources.calls[0],(unsigned long)f.sources.calls[1],
                (unsigned long)f.sources.calls[2],(unsigned long)f.sources.calls[3]);
        else if (!strcmp(command,"ADC BOUNDARY FIRST") || !strcmp(command,"ADC BOUNDARY WORST"))
            n=snprintf(out,size,"OK ADC BOUNDARY FRAME VALID=%u SEQ=%lu CNT=%lu,%lu DOWN=%u,%u REM=%lu WALL=%lu IRQ=%lu CPU=%lu MARGIN=%ld GEOM=%u HW_VERIFIED=0",
                f.valid,(unsigned long)f.seq,(unsigned long)f.entry_count,(unsigned long)f.exit_count,
                f.entry_down,f.exit_down,(unsigned long)f.remaining,(unsigned long)f.wall,
                (unsigned long)f.irq,(unsigned long)(f.wall>=f.irq ? f.wall-f.irq : 0U),
                (long)f.margin,f.geometry);
        return n>=0 && (uint32_t)n<size;
    }
#endif
    FocAdcTimingSnapshot s;
    FocAdcTiming_Snapshot(&s);
    int n = -1;
    if (strcmp(command, "ADC TIMING") == 0) {
        n = snprintf(out, size,
            "OK ADC TIMING IRQ=%lu PAIRS=%lu MISS=%lu LAST_CYC=%lu MAX_CYC=%lu LATE=%lu DWT=%u PF=%lu",
            (unsigned long)s.irq_entries, (unsigned long)s.pairs,
            (unsigned long)s.pair_misses, (unsigned long)s.last_cycles,
            (unsigned long)s.max_cycles, (unsigned long)s.deadline_misses,
            s.dwt_on, (unsigned long)s.plan_failures);
    } else if (strcmp(command, "ADC COMMIT") == 0) {
        n = snprintf(out, size,
            "OK ADC COMMIT RC=%u READY=%u CHECK=%lu FAIL=%lu BOTTOM_LATE=%lu GUARD=%u HW_VERIFIED=0",
#if defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
            1U,
#else
            0U,
#endif
            (unsigned)FocAdcTiming_RcActuationReady(), (unsigned long)s.commit_checks,
            (unsigned long)s.commit_failures, (unsigned long)s.deadline_misses,
            (unsigned)FOC_ADC_COMMIT_GUARD_TICKS);
    } else if (strcmp(command, "ADC BUFFER") == 0) {
        n = snprintf(out, size,
            "OK ADC BUFFER N=256 READY=%u BUSY=%u DONE=%lu DROP_B=%lu DROP_S=%lu REJECT=%lu MAX_CYC=%lu STK_VALID=%u FREE_B=%lu",
            s.buffers_ready, s.worker_busy, (unsigned long)s.processed_blocks,
            (unsigned long)s.dropped_blocks, (unsigned long)s.dropped_samples,
            (unsigned long)s.rejected_samples, (unsigned long)s.worker_max_cycles,
            s.worker_stack_valid, (unsigned long)s.worker_stack_free_bytes);
    } else if (strcmp(command, "ADC WINDOW") == 0) {
        n = snprintf(out, size,
            "OK ADC WINDOW SENSE=%u ST=%u READY=%u PLAN=%lu CMD4=%u SLACK=%u REF_MAX=95 SETTLE=%u RC_MIN=%u LATE=%u HW_VERIFIED=0",
            (unsigned)FOC_ADC_SENSE_TOPOLOGY, s.last_plan_status,
            (unsigned)FocAdcTiming_CanStart(),
            (unsigned long)s.plan_sequence, s.trigger, s.slack_ticks,
            (unsigned)FOC_ADC_SETTLE_TICKS, (unsigned)FOC_ADC_MIN_LOW_ON_TICKS,
            (unsigned)(FOC_ADC_SAMPLE_PLACEMENT == FOC_SAMPLE_LATE_BEFORE_PEAK));
    } else if (strcmp(command, "ADC SPREAD U") == 0 || strcmp(command, "ADC SPREAD V") == 0) {
        unsigned ch = command[11] == 'U' ? 0U : 1U;
        n = snprintf(out, size,
            "OK ADC SPREAD %c B=%lu N=%lu SUM=%lu SS=%lu MIN=%u MAX=%u STEP=%u MIX=%u CMDU=%u CMDV=%u CMDW=%u CMD4=%u",
            ch == 0U ? 'U' : 'V', (unsigned long)s.blocks,
            (unsigned long)s.raw.count, (unsigned long)s.raw.sum[ch],
            (unsigned long)s.raw.sum_sq[ch], s.raw.min[ch], s.raw.max[ch],
            s.raw.max_step[ch], s.mixed_block, s.command_phase[0],
            s.command_phase[1], s.command_phase[2], s.command_trigger);
    }
    return n >= 0 && (uint32_t)n < size;
}
