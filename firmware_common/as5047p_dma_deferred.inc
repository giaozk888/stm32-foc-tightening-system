/* Included only in the opt-in FOC-first STM32 port. TIM6_DAC is a verified
 * unused vector, software-pended only; its timer/DAC peripherals stay disabled.
 * Priority 4 bottom half owns protocol progression, parity/ERRFL and publication.
 * TIM2/RX/TX at 3 capture events only; ADC=2 can preempt all of them.
 * Sequence mailboxes avoid read/clear races when a top half interrupts service.
 * No new RTOS API, interrupt mask, busy wait, allocation or work loop. */
static volatile uint32_t defer_timer_seq,defer_rx_seq,defer_tx_seq;
static volatile uint32_t defer_rx_us,defer_rx_raw,defer_rx_error;
static volatile uint32_t defer_urgent;
#if defined(AS5047P_DMA_TERMINAL_FIX)
/* One aligned publication, serialized bottom-half owner. TIM2 observes it
 * before deciding a transaction timeout; independent control faults ignore it. */
static volatile uint32_t defer_terminal_claimed;
#endif
static uint32_t serviced_timer,serviced_rx,serviced_tx;
volatile uint32_t encoder_deferred_service_count,encoder_timer_event_count;
volatile uint32_t encoder_rx_event_count,encoder_tx_error_count,encoder_period_count;

static void DeferReset(void)
{
    defer_timer_seq=defer_rx_seq=defer_tx_seq=0U;
    serviced_timer=serviced_rx=serviced_tx=0U;
    defer_urgent=0U;
#if defined(AS5047P_DMA_TERMINAL_FIX)
    defer_terminal_claimed=0U;
#endif
    defer_fault_serviced=0U;
    defer_fault_flags_valid=0U;
    NVIC_ClearPendingIRQ(TIM6_DAC_IRQn);
}
FOC_RAM_PATH static void DeferOff(uint32_t reason)
{
    /* Error-only physical closure before deferred snapshots/reset. The existing
     * fault hook and status publication still run in the bottom half. */
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    DRIVER_SD_GPIO_Port->BSRR=(uint32_t)DRIVER_SD_Pin<<16U;
    if (!defer_urgent) defer_urgent=reason;
}
#if defined(AS5047P_DMA_TERMINAL_FIX)
FOC_RAM_PATH static int DeferBeginAllowed(void)
{
    if (defer_urgent) return 0; /* No implicit recovery after physical OFF. */
    defer_terminal_claimed=0U;
    __DMB();
    return defer_urgent==0U;
}
FOC_RAM_PATH static AsDmaStatus DeferTerminalClaim(AsDmaStatus status,uint32_t *now)
{
    if (status!=AS_DMA_OK) return status;
    *now=TIM2->CNT; /* Never backdate success to an old guard/service timestamp. */
    if (!defer_urgent && AsDma_TimeReached(*now,engine.deadline_us))
        DeferOff(AS_DMA_TIMEOUT);
    if (defer_urgent) return (AsDmaStatus)defer_urgent;
    /* If TIM2(3) preempts before this publication it wins and closes outputs;
     * after it, valid data has completed before deadline, even if callbacks
     * take us across that deadline. ADC may preempt but never opens gates. */
    __DMB();
    defer_terminal_claimed=1U;
    __DMB();
    if (defer_urgent) {
        *now=TIM2->CNT;
        return (AsDmaStatus)defer_urgent; /* Sticky OFF cannot become success. */
    }
    return AS_DMA_OK;
}
#endif
FOC_RAM_PATH static void DeferTimerTop(void)
{
    uint32_t now=TIM2->CNT;
    uint32_t enabled=TIM2->DIER;
    TIM2->SR=~(TIM_SR_CC1IF|TIM_SR_CC2IF|TIM_SR_CC3IF|TIM_SR_CC4IF);
    /* These are the SAME absolute deadline thresholds, not new limits. */
    if (periodic && (enabled&TIM_DIER_CC4IE) && AsDma_TimeReached(now,control_due_us))
        DeferOff(AS_DMA_CONTROL_STALE);
    else if ((enabled&TIM_DIER_CC1IE) && engine.state!=AS_DMA_IDLE &&
#if defined(AS5047P_DMA_TERMINAL_FIX)
             !defer_terminal_claimed &&
#endif
             AsDma_TimeReached(now,engine.deadline_us)) DeferOff(AS_DMA_TIMEOUT);
    ++encoder_timer_event_count;
    ++defer_timer_seq;
    __DMB(); NVIC_SetPendingIRQ(TIM6_DAC_IRQn);
}
FOC_RAM_PATH static void DeferRxTop(void)
{
    uint32_t flags=DMA1->ISR;
    if (!(flags&(DMA_ISR_TEIF4|DMA_ISR_TCIF4))) return;
    if (engine.state!=AS_DMA_WORD) { DMA1->IFCR=DMA_IFCR_CGIF4; return; }
    uint32_t spi_status=SPI1->SR;
    uint32_t error=(flags&DMA_ISR_TEIF4) || (flags&DMA_ISR_TEIF5) ||
        (spi_status&(SPI_SR_OVR|SPI_SR_MODF|SPI_SR_FRE));
    uint32_t now=TIM2->CNT;
    __DMB(); /* DMA completion precedes reading its SRAM payload. */
    uint16_t raw=engine.rx;
    if (error) {
        DeferOff(AS_DMA_IO);
        defer_fault_dma_isr=flags; defer_fault_spi_sr=spi_status;
        __DMB(); defer_fault_flags_valid=1U;
    }
    StopWord(0); /* bounded register acknowledgement, no protocol advancement */
    defer_rx_raw=raw; defer_rx_us=now; defer_rx_error=error;
    ++encoder_rx_event_count;
    __DMB(); ++defer_rx_seq; /* data-ready publication last */
    NVIC_SetPendingIRQ(TIM6_DAC_IRQn);
}
FOC_RAM_PATH static void DeferTxTop(void)
{
    uint32_t flags=DMA1->ISR;
    if (!(flags&DMA_ISR_TEIF5)) return;
    if (engine.state!=AS_DMA_WORD) { DMA1->IFCR=DMA_IFCR_CGIF5; return; }
    DeferOff(AS_DMA_IO);
    defer_fault_dma_isr=flags; defer_fault_spi_sr=SPI1->SR;
    __DMB(); defer_fault_flags_valid=1U;
    StopWord(0);
    ++encoder_tx_error_count;
    __DMB(); ++defer_tx_seq;
    NVIC_SetPendingIRQ(TIM6_DAC_IRQn);
}
FOC_RAM_PATH void TIM6_DAC_IRQHandler(void)
{
    ++encoder_deferred_service_count;
    uint32_t timer_event=defer_timer_seq,rx=defer_rx_seq,tx=defer_tx_seq;
    __DMB();
    uint32_t now=TIM2->CNT;
    if (defer_urgent) {
        if (!defer_fault_serviced) {
            defer_fault_serviced=1U;
            AsDma_Fail(&engine,(AsDmaStatus)defer_urgent,now);
        }
        serviced_rx=rx; serviced_tx=tx; serviced_timer=timer_event;
        return;
    }
    if (tx!=serviced_tx) {
        serviced_tx=tx;
        if (engine.state==AS_DMA_WORD) AsDma_Fail(&engine,AS_DMA_IO,now);
    }
    if (rx!=serviced_rx) {
        serviced_rx=rx;
        if (engine.state==AS_DMA_WORD) {
            /* Timestamp is RX IRQ receipt time (not a hardware-latched SPI
             * sample time), retaining the original timestamp convention.
             * Deadline and
             * CS post-clock guard are checked against service time. Never
             * backdate a guard to compensate for a delayed bottom half. */
            engine.rx=(uint16_t)defer_rx_raw;
            if (defer_rx_error) AsDma_Fail(&engine,AS_DMA_IO,now);
            else {
                AsDma_RxComplete(&engine,now);
                engine.word_rx_us=defer_rx_us;
            }
        }
    }
    serviced_timer=timer_event;
    AsDma_CheckDeadline(&engine,TIM2->CNT);
    now=TIM2->CNT;
    if (periodic && AsDma_TimeReached(now,control_due_us)) {
        AsDma_Fail(&engine,AS_DMA_CONTROL_STALE,now); return;
    }
    AsDma_Guard(&engine,now); /* necessary CS/protocol work, below FOC */
    now=TIM2->CNT;
    if (periodic && AsDma_TimeReached(now,next_period_us)) {
        if (now-next_period_us>=AS_DMA_SCHEDULE_LATE_US || engine.state!=AS_DMA_IDLE) {
            AsDma_Fail(&engine,AS_DMA_SCHEDULE,now); return;
        }
        next_period_us+=AS_DMA_PERIOD_US;
        ++encoder_period_count;
        Compare(&TIM2->CCR3,TIM_DIER_CC3IE,next_period_us);
        (void)AsDma_Begin(&engine,0x3FFFU,now);
    }
    /* If a top half arrived during this service its NVIC pending bit remains
     * set, causing another bounded invocation; no draining/catch-up loop. */
}
