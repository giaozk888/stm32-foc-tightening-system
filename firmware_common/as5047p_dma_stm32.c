#include "as5047p_dma_stm32.h"
#include "main.h"
#include "foc_hot_path.h"
#include "foc_fast_path_profile.h"
#include "foc_preempt_probe.h"
#include <string.h>
#if defined(FOC_FAST_MATH)
#include "foc_irq_load.h"
#endif

/* Dedicated resources, opt-in profile only:
 * DMA1 ch4 RX / ch5 TX; DMAMUX channels 3/4; TIM2 internal 1 MHz counter.
 * TIM2 CC1 deadline, CC2 CS/BSY guards, CC3 period, CC4 control watchdog.
 * Historic acquisition is priority 1 vs ADC 2 in the pipeline profile.
 * FOC-first: event IRQs 3, software-pended protocol service 4, ADC still 2;
 * TIM7 remains 3. No FreeRTOS API from any of these encoder IRQs.
 * No HAL_SPI DMA callback: its BSY tail may spin against HAL tick in an ISR. */
static AsDmaEngine engine;
static AsDmaFaultHook fault_hook;
static volatile uint8_t initialized, periodic;
static uint32_t next_period_us, control_due_us, saved_cr1, saved_cr2;
static uint32_t timeouts, dma_errors, schedule_misses, control_stale;
#if defined(AS5047P_DMA_TIMING_POLICY_V2)
static AsDmaTimingStats transaction_timing;
#endif
static volatile uint32_t diagnostic_fault_status;
uint32_t AS5047P_DmaFaultStatus(void) { return diagnostic_fault_status; }
static AsDmaFaultSnapshot first_fault;
#if defined(AS5047P_DMA_FOC_FIRST)
#include "as5047p_dma_publication.h"
static AsDmaPublication publication;
/* Error-only flags preserved before the event top half acknowledges DMA. */
static uint32_t defer_fault_dma_isr,defer_fault_spi_sr;
static volatile uint32_t defer_fault_flags_valid;
static uint32_t defer_fault_serviced;
#if defined(AS5047P_DMA_TERMINAL_FIX)
static AsDmaStatus DeferTerminalClaim(AsDmaStatus status,uint32_t *now);
static int DeferBeginAllowed(void);
#define AS_DMA_TERMINAL_CLAIM(e,status,now) DeferTerminalClaim(status,now)
#define AS_DMA_BEGIN_ALLOWED(e) DeferBeginAllowed()
#endif
#define AS_DMA_IRQ_PRIORITY 3U
#elif defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
/* Encoder deadline/guard preempts ADC(2). TIM7 is 3 in the pipeline and
 * 0 in the legacy profile. This IRQ also owns transaction/control deadlines;
 * do not demote it based solely on a partial timing snapshot. */
#define AS_DMA_IRQ_PRIORITY 1U
static uint32_t tim_entry_us, tim_entry_sr, tim_entry_dier, tim_entry_ccr2;
static uint32_t tim_entry_late_us, guard_max_late_us;
#else
#define AS_DMA_IRQ_PRIORITY 3U
#endif

static uint32_t Lock(void) { uint32_t mask = __get_PRIMASK(); __disable_irq(); return mask; }
static void Unlock(uint32_t mask) { __DMB(); __set_PRIMASK(mask); }
FOC_RAM_PATH uint32_t AS5047P_DmaNowUs(void) { return TIM2->CNT; }

FOC_RAM_PATH static void Compare(volatile uint32_t *ccr, uint32_t flag, uint32_t due)
{
    TIM2->DIER &= ~flag;
    TIM2->SR = ~flag;
    *ccr = due;
    TIM2->DIER |= flag; /* CCxIF and CCxIE share the same bit positions */
    __DSB();
    if (AsDma_TimeReached(TIM2->CNT, due)) NVIC_SetPendingIRQ(TIM2_IRQn);
}

FOC_RAM_PATH static void Cs(void *context, int high)
{
    (void)context;
    AS5047_CS_GPIO_Port->BSRR = high ? AS5047_CS_Pin : ((uint32_t)AS5047_CS_Pin << 16U);
}
FOC_RAM_PATH static void Guard(void *context, uint32_t due)
{
    (void)context; Compare(&TIM2->CCR2, TIM_DIER_CC2IE, due);
}
FOC_RAM_PATH static void Deadline(void *context, int enable, uint32_t due)
{
    (void)context;
    if (enable) Compare(&TIM2->CCR1, TIM_DIER_CC1IE, due);
    else { TIM2->DIER &= ~TIM_DIER_CC1IE; TIM2->SR = ~TIM_SR_CC1IF; }
}
FOC_RAM_PATH static void StopWord(void *context)
{
    (void)context;
    SPI1->CR2 &= ~(SPI_CR2_TXDMAEN | SPI_CR2_RXDMAEN);
    DMA1_Channel4->CCR = 0U;
    DMA1_Channel5->CCR = 0U;
    __DSB();
    DMA1->IFCR = DMA_IFCR_CGIF4 | DMA_IFCR_CGIF5;
    NVIC_ClearPendingIRQ(DMA1_Channel4_IRQn);
    NVIC_ClearPendingIRQ(DMA1_Channel5_IRQn);
}
FOC_RAM_PATH static int Busy(void *context) { (void)context; return (SPI1->SR & SPI_SR_BSY) != 0U; }

FOC_RAM_PATH static int StartWord(void *context, volatile uint16_t *tx, volatile uint16_t *rx)
{
    (void)context;
    if ((SPI1->SR & (SPI_SR_BSY | SPI_SR_OVR | SPI_SR_MODF | SPI_SR_FRE | SPI_SR_FRLVL)) ||
        (DMA1_Channel4->CCR & DMA_CCR_EN) || (DMA1_Channel5->CCR & DMA_CCR_EN)) return 0;
    DMA1->IFCR = DMA_IFCR_CGIF4 | DMA_IFCR_CGIF5;
    NVIC_ClearPendingIRQ(DMA1_Channel4_IRQn);
    NVIC_ClearPendingIRQ(DMA1_Channel5_IRQn);
    *rx = 0U;
    DMA1_Channel4->CPAR = (uint32_t)&SPI1->DR;
    DMA1_Channel4->CMAR = (uint32_t)rx;
    DMA1_Channel4->CNDTR = 1U;
    DMA1_Channel5->CPAR = (uint32_t)&SPI1->DR;
    DMA1_Channel5->CMAR = (uint32_t)tx;
    DMA1_Channel5->CNDTR = 1U;
    __DMB();
    /* RX first. 16-bit peripheral and memory width; one word, no circular DMA. */
    DMA1_Channel4->CCR = DMA_CCR_PL_1 | DMA_CCR_PSIZE_0 | DMA_CCR_MSIZE_0 |
                         DMA_CCR_TCIE | DMA_CCR_TEIE | DMA_CCR_EN;
    SPI1->CR1 |= SPI_CR1_SPE;
    SPI1->CR2 |= SPI_CR2_RXDMAEN;
    DMA1_Channel5->CCR = DMA_CCR_PL_1 | DMA_CCR_PSIZE_0 | DMA_CCR_MSIZE_0 |
                         DMA_CCR_DIR | DMA_CCR_TEIE | DMA_CCR_EN;
    SPI1->CR2 |= SPI_CR2_TXDMAEN;
    return 1;
}

FOC_RAM_PATH static void Finish(void *context, AsDmaStatus status)
{
    (void)context;
    TIM2->DIER &= ~TIM_DIER_CC2IE;
    TIM2->SR = ~TIM_SR_CC2IF;
#if defined(AS5047P_DMA_FOC_FIRST)
    AsDma_Publish(&publication,&engine.sample);
    if (status!=AS_DMA_OK && status!=AS_DMA_CANCELLED) defer_fault_serviced=1U;
#endif
    if (status == AS_DMA_OK) {
#if defined(AS5047P_DMA_TIMING_POLICY_V2)
        AsDmaTiming_Record(&transaction_timing,&engine.sample);
#endif
        return;
    }
    /* Fixed register sequence, no HAL abort or BSY wait. Restore SPI config
     * after reset so neither a partial word nor stale FIFO crosses epochs. */
    __HAL_RCC_SPI1_FORCE_RESET();
    __DSB();
    __HAL_RCC_SPI1_RELEASE_RESET();
    SPI1->CR1 = saved_cr1;
    SPI1->CR2 = saved_cr2;
    if (status == AS_DMA_TIMEOUT) ++timeouts;
    if (status == AS_DMA_IO) ++dma_errors;
    if (status == AS_DMA_SCHEDULE) ++schedule_misses;
    if (status == AS_DMA_CONTROL_STALE) ++control_stale;
    if (periodic) {
        periodic = 0U;
        TIM2->DIER &= ~(TIM_DIER_CC3IE | TIM_DIER_CC4IE);
        if (fault_hook) fault_hook();
    }
}
FOC_RAM_PATH static void FaultSnapshot(void *context, const AsDmaEngine *e,
                          AsDmaStatus status, uint32_t now)
{
    (void)context;
    diagnostic_fault_status=(uint32_t)status;
    /* The fault snapshot adds register reads to the fault path. Close the
     * physical output through the existing ISR-safe hook FIRST; Finish()
     * sees periodic=0 and does not invoke it a second time. */
    if (periodic != 0U) {
        if (fault_hook) fault_hook();
        periodic = 0U;
        TIM2->DIER &= ~(TIM_DIER_CC3IE | TIM_DIER_CC4IE);
    }
    if (first_fault.valid != 0U) return;
    first_fault.status = (uint32_t)status;
    first_fault.phase = (uint32_t)e->state;
    first_fault.frame = e->frame;
    first_fault.started_us = e->started_us;
    first_fault.now_us = now;
    first_fault.deadline_us = e->deadline_us;
    first_fault.guard_us = e->guard_us;
    first_fault.spi_sr = SPI1->SR;
    first_fault.spi_cr1 = SPI1->CR1;
    first_fault.spi_cr2 = SPI1->CR2;
    first_fault.dma_isr = DMA1->ISR;
#if defined(AS5047P_DMA_FOC_FIRST)
    if (defer_fault_flags_valid) {
        first_fault.spi_sr=defer_fault_spi_sr;
        first_fault.dma_isr=defer_fault_dma_isr;
    }
#endif
    first_fault.rx_ndtr = DMA1_Channel4->CNDTR;
    first_fault.tx_ndtr = DMA1_Channel5->CNDTR;
    first_fault.rx_ccr = DMA1_Channel4->CCR;
    first_fault.tx_ccr = DMA1_Channel5->CCR;
    first_fault.tim_sr = TIM2->SR;
    first_fault.tim_dier = TIM2->DIER;
    first_fault.ipsr = __get_IPSR();
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC) && !defined(AS5047P_DMA_FOC_FIRST)
    if (first_fault.ipsr == (uint32_t)TIM2_IRQn + 16U) {
        first_fault.tim_entry_valid = 1U;
        first_fault.tim_entry_us = tim_entry_us;
        first_fault.tim_entry_sr = tim_entry_sr;
        first_fault.tim_entry_dier = tim_entry_dier;
        first_fault.tim_entry_ccr2 = tim_entry_ccr2;
        first_fault.tim_entry_late_us = tim_entry_late_us;
    }
    first_fault.guard_max_late_us = guard_max_late_us;
#endif
    __DMB();
    first_fault.valid = 1U; /* publish only after every field is captured */
}
#if !defined(FOC_IRQ_COMPACT)
static const AsDmaOps ops = {
    Cs, Guard, Deadline, StartWord, StopWord, Busy, Finish, FaultSnapshot
};
#endif

#if defined(FOC_IRQ_COMPACT)
/* Compile the engine ONCE in this translation unit with fixed callbacks. This
 * exposes register hooks to O2 inlining/devirtualization, not a second driver.
 * FaultSnapshot still precedes StopWord; CS/deadlines/guards are unchanged. */
#define AS_DMA_BIND_cs Cs
#define AS_DMA_BIND_guard Guard
#define AS_DMA_BIND_deadline Deadline
#define AS_DMA_BIND_start_word StartWord
#define AS_DMA_BIND_stop_word StopWord
#define AS_DMA_BIND_busy Busy
#define AS_DMA_BIND_finish Finish
#define AS_DMA_BIND_fault_snapshot FaultSnapshot
#define AS_DMA_BIND(name, e) AS_DMA_BIND_##name
#define AS_DMA_HAS_FAULT_SNAPSHOT(e) 1
#include "as5047p_dma_engine.c"
#endif

#if defined(AS5047P_DMA_FOC_FIRST)
#include "as5047p_dma_deferred.inc"
#endif

int AS5047P_DmaInit(AsDmaFaultHook hook)
{
    uint32_t timer_hz = HAL_RCC_GetPCLK1Freq();
    if ((RCC->CFGR & RCC_CFGR_PPRE1) != 0U) timer_hz *= 2U;
    /* Conservatively require G474 DMA-visible SRAM1/2, not CCM aliases. */
    if (timer_hz % 1000000U || timer_hz < 1000000U ||
        (uint32_t)&engine.tx < 0x20000000U || (uint32_t)&engine.rx + 2U > 0x20018000U ||
        (SPI1->CR2 & SPI_CR2_DS) != SPI_CR2_DS || (SPI1->SR & SPI_SR_BSY) ||
        (TIM2->CR1 & TIM_CR1_CEN) || (DMA1_Channel4->CCR & DMA_CCR_EN) ||
        (DMA1_Channel5->CCR & DMA_CCR_EN)) return 0;
    fault_hook = hook;
    saved_cr1 = SPI1->CR1 & ~SPI_CR1_SPE;
    saved_cr2 = SPI1->CR2 & ~(SPI_CR2_RXDMAEN | SPI_CR2_TXDMAEN |
                            SPI_CR2_RXNEIE | SPI_CR2_TXEIE | SPI_CR2_ERRIE);
    __HAL_RCC_DMA1_CLK_ENABLE();
    __HAL_RCC_DMAMUX1_CLK_ENABLE();
    __HAL_RCC_TIM2_CLK_ENABLE();
    DMA1_Channel4->CCR = DMA1_Channel5->CCR = 0U;
    DMAMUX1_Channel3->CCR = DMA_REQUEST_SPI1_RX;
    DMAMUX1_Channel4->CCR = DMA_REQUEST_SPI1_TX;
    TIM2->CR1 = 0U;
    TIM2->DIER = 0U;
    TIM2->PSC = timer_hz / 1000000U - 1U;
    TIM2->ARR = 0xFFFFFFFFU;
    TIM2->CCMR1 = TIM2->CCMR2 = TIM2->CCER = 0U;
    TIM2->EGR = TIM_EGR_UG;
    TIM2->SR = 0U;
    TIM2->CNT = 0U;
    TIM2->CR1 = TIM_CR1_CEN;
#if defined(FOC_IRQ_COMPACT)
    /* No live dispatch table in the fixed single-port engine. This also lets
     * GCC remove callbacks whose entire register sequence was inlined. */
    AsDma_Init(&engine, 0, 0);
#else
    AsDma_Init(&engine, &ops, 0);
#endif
    memset(&first_fault, 0, sizeof(first_fault));
#if defined(AS5047P_DMA_FOC_FIRST)
    memset(&publication,0,sizeof(publication));
    publication.bank[0].status=AS_DMA_PENDING;
    publication.bank[1].status=AS_DMA_PENDING;
    DeferReset();
    /* No timer/DAC clock or hardware source is enabled for this vector. */
    if (NVIC_GetEnableIRQ(TIM6_DAC_IRQn)) return 0;
    HAL_NVIC_SetPriority(TIM6_DAC_IRQn,4U,0U);
    HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn);
#elif defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
    tim_entry_us = tim_entry_sr = tim_entry_dier = tim_entry_ccr2 = 0U;
    tim_entry_late_us = guard_max_late_us = 0U;
#endif
    Cs(0, 1);
    StopWord(0);
    HAL_NVIC_SetPriority(TIM2_IRQn, AS_DMA_IRQ_PRIORITY, 0U);
    HAL_NVIC_SetPriority(DMA1_Channel4_IRQn, AS_DMA_IRQ_PRIORITY, 0U);
    HAL_NVIC_SetPriority(DMA1_Channel5_IRQn, AS_DMA_IRQ_PRIORITY, 0U);
    NVIC_ClearPendingIRQ(TIM2_IRQn);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
    HAL_NVIC_EnableIRQ(DMA1_Channel4_IRQn);
    HAL_NVIC_EnableIRQ(DMA1_Channel5_IRQn);
    initialized = 1U;
    return 1;
}

int AS5047P_DmaStartPeriodic(void)
{
    uint32_t mask = Lock(), now = TIM2->CNT;
    int ok = initialized && !periodic && engine.state == AS_DMA_IDLE;
    if (ok) {
        engine.sample.status = AS_DMA_PENDING;
#if defined(AS5047P_DMA_FOC_FIRST)
        DeferReset();
        AsDma_Publish(&publication,&engine.sample);
#endif
        periodic = 1U;
        next_period_us = now + AS_DMA_PERIOD_US;
        control_due_us = now + AS_DMA_CONTROL_WATCHDOG_US;
        Compare(&TIM2->CCR3, TIM_DIER_CC3IE, next_period_us);
        Compare(&TIM2->CCR4, TIM_DIER_CC4IE, control_due_us);
        ok = AsDma_Begin(&engine, 0x3FFFU, now);
    }
    Unlock(mask);
    return ok;
}
void AS5047P_DmaStopPeriodic(void)
{
    uint32_t mask = Lock();
    periodic = 0U; /* cancellation in SAFE is not a newly raised fault */
#if defined(AS5047P_DMA_FOC_FIRST)
    DeferReset();
#endif
    TIM2->DIER &= ~(TIM_DIER_CC3IE | TIM_DIER_CC4IE);
    if (engine.state != AS_DMA_IDLE) AsDma_Fail(&engine, AS_DMA_CANCELLED, TIM2->CNT);
    Unlock(mask);
}
int AS5047P_DmaIsPeriodic(void) { return periodic != 0U; }
int AS5047P_DmaGetSample(AsDmaSample *sample)
{
#if defined(AS5047P_DMA_FOC_FIRST)
    if (!initialized || sample==NULL || !AsDma_ReadPublished(&publication,sample)) return 0;
    return sample->status!=AS_DMA_PENDING;
#else
    uint32_t mask = Lock();
    if (initialized) AsDma_CheckDeadline(&engine, TIM2->CNT);
    *sample = engine.sample;
    int available = initialized && sample->status != AS_DMA_PENDING;
    Unlock(mask);
    return available;
#endif
}
int AS5047P_DmaSnapshot(AsDmaSample *sample, uint32_t *now_us)
{
    if (sample == NULL || now_us == NULL) return 0;
#if defined(AS5047P_DMA_FOC_FIRST)
    if (!initialized || !AsDma_ReadPublished(&publication,sample)) return 0;
    *now_us=TIM2->CNT;
    return sample->sequence!=0U && sample->status!=AS_DMA_PENDING;
#else
    uint32_t mask = Lock();
    *sample = engine.sample;
    *now_us = TIM2->CNT;
    int available = initialized && sample->sequence != 0U && sample->status != AS_DMA_PENDING;
    Unlock(mask);
    return available;
#endif
}
void AS5047P_DmaAcknowledgeControl(void)
{
    uint32_t mask = Lock();
    if (periodic) {
        uint32_t now = TIM2->CNT;
        /* A delayed IRQ must not let a late task extend an expired watchdog. */
        if (AsDma_TimeReached(now, control_due_us))
            AsDma_Fail(&engine, AS_DMA_CONTROL_STALE, now);
        else {
            control_due_us = now + AS_DMA_CONTROL_WATCHDOG_US;
            Compare(&TIM2->CCR4, TIM_DIER_CC4IE, control_due_us);
        }
    }
    Unlock(mask);
}
void AS5047P_DmaGetStats(AsDmaStats *s)
{
    uint32_t mask = Lock();
    *s = (AsDmaStats){engine.attempts, engine.successes, engine.failures, engine.max_elapsed_us,
        timeouts, dma_errors, schedule_misses, control_stale, engine.sample.elapsed_us,
        (uint32_t)engine.sample.status, periodic};
    Unlock(mask);
}
#if defined(AS5047P_DMA_TIMING_POLICY_V2)
void AS5047P_DmaGetTimingStats(uint32_t *slow_count,uint32_t *ok_max_us)
{
    uint32_t mask=Lock();
    *slow_count=transaction_timing.slow_count;*ok_max_us=transaction_timing.ok_max_us;
    Unlock(mask);
}
#endif
void AS5047P_DmaGetFaultSnapshot(AsDmaFaultSnapshot *snapshot)
{
    if (snapshot == NULL) return;
    uint32_t mask = Lock();
    *snapshot = first_fault;
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC) && !defined(AS5047P_DMA_FOC_FIRST)
    snapshot->guard_max_late_us = guard_max_late_us;
#endif
    Unlock(mask);
}

AsDmaStatus AS5047P_DmaReadOne(uint16_t reg, uint16_t *response)
{
    uint32_t mask = Lock(), sequence = engine.sample.sequence;
#if defined(AS5047P_DMA_FOC_FIRST)
    if (!periodic) DeferReset();
#endif
    int started = initialized && !periodic && AsDma_Begin(&engine, reg, TIM2->CNT);
    Unlock(mask);
    if (!started) return AS_DMA_IO;
    /* Only startup / explicitly SAFE single-read diagnostics use this adapter.
     * A fixed iteration cap also covers a stopped timer; no unbounded while. */
    for (unsigned i = 0; i < 8192U; ++i) {
        AsDmaSample sample;
        if (AS5047P_DmaGetSample(&sample) && sample.sequence != sequence) {
            if (sample.status == AS_DMA_OK && response) *response = sample.response;
            return sample.status;
        }
        __NOP();
    }
    mask = Lock();
    if (engine.sample.sequence != sequence) {
        AsDmaStatus result = engine.sample.status;
        if (result == AS_DMA_OK && response) *response = engine.sample.response;
        Unlock(mask);
        return result;
    }
    AsDma_Fail(&engine, AS_DMA_TIMEOUT, TIM2->CNT);
    Unlock(mask);
    return AS_DMA_TIMEOUT;
}

#if defined(FOC_FAST_MATH)
/* Wrappers cover every early return without changing default IRQ bodies. */
#define DMA1_Channel4_IRQHandler EncoderDma_RxIrqBody
#define DMA1_Channel5_IRQHandler EncoderDma_TxIrqBody
#define TIM2_IRQHandler EncoderDma_TimerIrqBody
#endif
FOC_RAM_PATH void DMA1_Channel4_IRQHandler(void)
{
#if defined(AS5047P_DMA_FOC_FIRST)
    DeferRxTop();
#else
    uint32_t flags = DMA1->ISR;
    if (flags & DMA_ISR_TEIF4) {
        if (engine.state == AS_DMA_WORD) AsDma_Fail(&engine, AS_DMA_IO, TIM2->CNT);
        else DMA1->IFCR = DMA_IFCR_CGIF4;
    } else if (flags & DMA_ISR_TCIF4) {
        DMA1->IFCR = DMA_IFCR_CGIF4;
        __DMB();
        if (engine.state != AS_DMA_WORD) return; /* old epoch / spurious IRQ */
        if ((DMA1->ISR & DMA_ISR_TEIF5) ||
            (SPI1->SR & (SPI_SR_OVR | SPI_SR_MODF | SPI_SR_FRE)))
            AsDma_Fail(&engine, AS_DMA_IO, TIM2->CNT);
        else AsDma_RxComplete(&engine, TIM2->CNT);
    }
#endif
}
FOC_RAM_PATH void DMA1_Channel5_IRQHandler(void)
{
#if defined(AS5047P_DMA_FOC_FIRST)
    DeferTxTop();
#else
    uint32_t flags = DMA1->ISR;
    if (flags & DMA_ISR_TEIF5) {
        if (engine.state == AS_DMA_WORD) AsDma_Fail(&engine, AS_DMA_IO, TIM2->CNT);
        else DMA1->IFCR = DMA_IFCR_CGIF5;
    }
#endif
}
FOC_RAM_PATH void TIM2_IRQHandler(void)
{
#if defined(AS5047P_DMA_FOC_FIRST)
    DeferTimerTop();
#else
    uint32_t now = TIM2->CNT;
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
    /* Preserve the evidence that the earlier trace lost by clearing CC2 at
     * IRQ entry. Reading the already latched status does not acknowledge it. */
    tim_entry_us = now;
    tim_entry_sr = TIM2->SR;
    tim_entry_dier = TIM2->DIER;
    tim_entry_ccr2 = TIM2->CCR2;
    tim_entry_late_us = ((tim_entry_dier & TIM_DIER_CC2IE) != 0U &&
                         AsDma_TimeReached(now, tim_entry_ccr2)) ?
                        now - tim_entry_ccr2 : 0U;
    if (tim_entry_late_us > guard_max_late_us)
        guard_max_late_us = tim_entry_late_us;
#endif
    /* Ignore disabled/stale compare flags; recheck absolute times even when
     * compare programming was preempted and software-pended this IRQ. */
    TIM2->SR = ~(TIM_SR_CC1IF | TIM_SR_CC2IF | TIM_SR_CC3IF | TIM_SR_CC4IF);
    AsDma_CheckDeadline(&engine, now);
    if (periodic && AsDma_TimeReached(now, control_due_us)) {
        AsDma_Fail(&engine, AS_DMA_CONTROL_STALE, now);
        return;
    }
    AsDma_Guard(&engine, TIM2->CNT);
    now = TIM2->CNT;
    if (periodic && AsDma_TimeReached(now, next_period_us)) {
        if (now - next_period_us >= AS_DMA_SCHEDULE_LATE_US || engine.state != AS_DMA_IDLE) {
            AsDma_Fail(&engine, AS_DMA_SCHEDULE, now);
            return; /* no burst of catch-up samples */
        }
        next_period_us += AS_DMA_PERIOD_US;
        Compare(&TIM2->CCR3, TIM_DIER_CC3IE, next_period_us);
        (void)AsDma_Begin(&engine, 0x3FFFU, now);
    }
#endif
}
#if defined(FOC_FAST_MATH)
#undef DMA1_Channel4_IRQHandler
#undef DMA1_Channel5_IRQHandler
#undef TIM2_IRQHandler
FOC_RAM_PATH void DMA1_Channel4_IRQHandler(void)
{
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreToken token=FocPreempt_IrqBegin(FOC_PRE_RX);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    uint32_t profile_irq_begin=DWT->CYCCNT;
#endif
#if defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
    FocIrqSource_Enter(FOC_IRQ_RX); EncoderDma_RxIrqBody(); FocIrqSource_Leave(FOC_IRQ_RX);
#elif !FOC_DETAIL_STATS || defined(AS5047P_DMA_FOC_FIRST)
    EncoderDma_RxIrqBody();
#else
    FocIrqLoad_Enter(); EncoderDma_RxIrqBody(); FocIrqLoad_Leave();
#endif
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreempt_IrqEnd(FOC_PRE_RX,token);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    FocProfile_IrqRecord(2U,profile_irq_begin);
#endif
}
FOC_RAM_PATH void DMA1_Channel5_IRQHandler(void)
{
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreToken token=FocPreempt_IrqBegin(FOC_PRE_TX);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    uint32_t profile_irq_begin=DWT->CYCCNT;
#endif
#if defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
    FocIrqSource_Enter(FOC_IRQ_TX); EncoderDma_TxIrqBody(); FocIrqSource_Leave(FOC_IRQ_TX);
#elif !FOC_DETAIL_STATS || defined(AS5047P_DMA_FOC_FIRST)
    EncoderDma_TxIrqBody();
#else
    FocIrqLoad_Enter(); EncoderDma_TxIrqBody(); FocIrqLoad_Leave();
#endif
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreempt_IrqEnd(FOC_PRE_TX,token);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    FocProfile_IrqRecord(3U,profile_irq_begin);
#endif
}
FOC_RAM_PATH void TIM2_IRQHandler(void)
{
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreToken token=FocPreempt_IrqBegin(FOC_PRE_TIMER);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    uint32_t profile_irq_begin=DWT->CYCCNT;
#endif
#if defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
    FocIrqSource_Enter(FOC_IRQ_TIMER); EncoderDma_TimerIrqBody(); FocIrqSource_Leave(FOC_IRQ_TIMER);
#elif !FOC_DETAIL_STATS || defined(AS5047P_DMA_FOC_FIRST)
    EncoderDma_TimerIrqBody();
#else
    FocIrqLoad_Enter(); EncoderDma_TimerIrqBody(); FocIrqLoad_Leave();
#endif
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreempt_IrqEnd(FOC_PRE_TIMER,token);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    FocProfile_IrqRecord(1U,profile_irq_begin);
#endif
}
#endif
