#include "main.h"
#include "foc_adc_timing_stm32.h"
#include "foc_adc_clock_stm32.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
TIM_TypeDef mock_tim;
ADC_TypeDef mock_adc1, mock_adc2;
DWT_Type mock_dwt;
uint32_t mock_primask;
uint32_t mock_ipsr;
uint32_t mock_hclk = 170000000;
uint32_t mock_sysclk = 170000000;
uint32_t mock_adc_clock_source = RCC_ADC12CLKSOURCE_SYSCLK;
ADC_Common_TypeDef mock_adc_common;
RCC_TypeDef mock_rcc;
uint32_t mock_frequency_reads;
int main(void)
{
    assert(!FocAdcTiming_CanStart());
#if FOC_ADC_SENSE_TOPOLOGY == 0
    mock_tim.CCR4 = 3500;
    assert(FocAdcTiming_Commit(.5f,.5f,.5f) == FOC_WINDOW_TOPOLOGY_UNKNOWN);
    assert(!FocAdcTiming_CanStart() && mock_tim.CCR4 == 3500);
    puts("PASS: unknown topology cannot commit/start");
    return 0;
#else
    mock_tim.ARR = FOC_ADC_TIMER_ARR;
    mock_tim.BDTR = 85;
    mock_tim.CR1 = TIM_COUNTERMODE_CENTERALIGNED1;
    mock_tim.CCMR1 = TIM_CCMR1_OC1PE | TIM_CCMR1_OC2PE;
    mock_tim.CCMR2 = TIM_CCMR2_OC3PE | TIM_CCMR2_OC4PE;
    mock_tim.CR2 = TIM_TRGO2_OC4REF;
    mock_adc_common.CCR = FOC_ADC_CLOCK_PRESCALER;
    FocAdcTimingSnapshot initial;
#if defined(FOC_ADC_RC_DIAGNOSTIC)
    assert(FocAdcTiming_Commit(.95f,.95f,.95f) == FOC_WINDOW_TOO_SHORT);
    assert(mock_tim.CCR1 == 0 && mock_tim.CCR4 == 0 && !FocAdcTiming_CanStart());
    assert(FocAdcTiming_Commit(.5f,.5f,.5f) == FOC_WINDOW_OK);
    assert(mock_tim.CCR1 == 2125 && mock_tim.CCR4 == 4184);
    FocAdcTiming_Snapshot(&initial);
    assert(initial.slack_ticks == 274 && initial.plan_failures == 1);
#else
    assert(FocAdcTiming_Commit(.95f,.95f,.95f) == FOC_WINDOW_OK);
    assert(mock_tim.CCR1 == 4037 && mock_tim.CCR4 == 4217);
    FocAdcTiming_Snapshot(&initial);
    assert(initial.slack_ticks == 20);
#endif
    assert(mock_tim.EGR == TIM_EGR_UG && mock_tim.CNT == 0);
    assert(FocAdcTiming_CanStart() && mock_primask == 0);
    assert(!FocAdcTiming_FastCanStart());
    assert(FocAdcTiming_CertifyClock());
    uint32_t freq_reads=mock_frequency_reads;
    assert(FocAdcTiming_FastCanStart());
    assert(mock_frequency_reads==freq_reads);
    volatile uint32_t *clock_fields[]={&mock_rcc.CR,&mock_rcc.CFGR,&mock_rcc.PLLCFGR,&mock_rcc.ICSCR};
    for (unsigned field=0;field<4;++field) {
        *clock_fields[field]^=1U; assert(!FocAdcTiming_FastCanStart());
        *clock_fields[field]^=1U; assert(FocAdcTiming_FastCanStart());
    }
    mock_adc_common.CCR=0U; assert(!FocAdcTiming_FastCanStart());
    mock_adc_common.CCR=FOC_ADC_CLOCK_PRESCALER;
    mock_adc_clock_source=0U; assert(!FocAdcTiming_FastCanStart());
    mock_adc_clock_source=RCC_ADC12CLKSOURCE_SYSCLK;
    mock_ipsr=18U; assert(!FocAdcTiming_CertifyClock() && !FocAdcTiming_FastCanStart());
    mock_ipsr=0U; assert(FocAdcTiming_CertifyClock());
    mock_primask=1U; assert(!FocAdcTiming_CertifyClock());
    mock_primask=0U; assert(FocAdcTiming_CertifyClock());
    FocWindowPlan prepared;
    uint32_t old_ccr=mock_tim.CCR4;
    assert(FocAdcTiming_Prepare(.5f,.5f,.5f,&prepared)==FOC_WINDOW_OK);
    assert(mock_tim.CCR4==old_ccr && !mock_primask);
    FocAdcTiming_CommitPrepared(&prepared);
    assert(mock_tim.CCR4==prepared.trigger && !mock_primask);
    /* Reject every unexpected clock/prescaler combination, not just /4. */
    for (unsigned presc = 0; presc < 16; ++presc) {
        for (unsigned mode = 0; mode < 4; ++mode) {
            mock_adc_common.CCR = (presc << 18) | (mode << 16);
            assert(FocAdcTiming_CanStart() == (presc == 2 && mode == 0));
        }
    }
    mock_adc_common.CCR = FOC_ADC_CLOCK_PRESCALER | (1U << 22);
    assert(FocAdcTiming_CanStart()); /* VREFINT enable is unrelated. */
    mock_adc_clock_source = 1U << 28;
    assert(!FocAdcTiming_CanStart());
    mock_adc_clock_source = RCC_ADC12CLKSOURCE_SYSCLK;
    mock_sysclk = 85000000;
    assert(!FocAdcTiming_CanStart());
    mock_sysclk = 170000000;
    assert(FocAdcTiming_CanStart());
    mock_hclk = 85000000;
    assert(!FocAdcTiming_CanStart());
    mock_hclk = 170000000;
    mock_tim.CCMR2 = 0;
    assert(!FocAdcTiming_CanStart());
    assert(!FocAdcTiming_FastCanStart());
    mock_tim.CCMR2 = TIM_CCMR2_OC3PE | TIM_CCMR2_OC4PE;
    mock_tim.EGR = 0;
    mock_tim.CR1 = TIM_CR1_CEN | TIM_CR1_UDIS;
    mock_primask = 1;
    assert(FocAdcTiming_Commit(.5f,.5f,.5f) == FOC_WINDOW_OK);
    assert(mock_tim.EGR == 0 && mock_tim.CR1 == (TIM_CR1_CEN | TIM_CR1_UDIS));
    assert(mock_primask == 1);
    mock_adc1.ISR = ADC_ISR_JEOS;
    assert(!FocAdcTiming_PairReady());
    mock_adc2.ISR = ADC_ISR_JEOS;
    assert(FocAdcTiming_PairReady());
    mock_dwt.CTRL = 1;
    mock_dwt.CYCCNT = UINT32_MAX - 19U;
    uint32_t start = FocAdcTiming_IrqEnter();
    mock_dwt.CYCCNT = 30;
    FocAdcTiming_IrqExit(start);
    for (unsigned i=0; i<256; ++i) FocAdcTiming_RecordRaw(2048,2049);
    FocAdcTimingSnapshot s;
    FocAdcTiming_Snapshot(&s);
    assert(s.blocks == 0 && s.raw.count == 0 && s.buffers_ready == 1);
    assert(!FocAdcTiming_ProcessRawOne()); /* Caller left interrupts masked. */
    assert(mock_primask == 1);
    mock_primask = 0;
    mock_ipsr = 34;
    assert(!FocAdcTiming_ProcessRawOne()); /* ISR cannot compute statistics. */
    mock_ipsr = 0;
    assert(FocAdcTiming_ProcessRawOne());
    assert(!FocAdcTiming_ProcessRawOne());
    FocAdcTiming_Snapshot(&s);
    assert(s.irq_entries == 1 && s.pairs == 256 && s.pair_misses == 1);
    assert(s.last_cycles == 50 && s.max_cycles == 50 && s.blocks == 1);
    assert(s.raw.count == 256 && s.raw.sum[0] == 524288 && !s.mixed_block);
    for (unsigned i=0; i<128; ++i) FocAdcTiming_RecordRaw(2048,2049);
#if defined(FOC_ADC_RC_DIAGNOSTIC)
    assert(FocAdcTiming_Commit(.52f,.5f,.48f) == FOC_WINDOW_OK);
#else
    assert(FocAdcTiming_Commit(.9f,.5f,.1f) == FOC_WINDOW_OK);
#endif
    for (unsigned i=0; i<128; ++i) FocAdcTiming_RecordRaw(2048,2049);
    assert(FocAdcTiming_ProcessRawOne());
    FocAdcTiming_Snapshot(&s);
    assert(s.mixed_block && s.blocks == 2);
    char out[192];
    assert(FocAdcTiming_Format("ADC TIMING",out,sizeof(out)));
    assert(strstr(out,"IRQ=1") != NULL);
    assert(FocAdcTiming_Format("ADC SPREAD U",out,sizeof(out)));
    assert(strstr(out,"SUM=524288") != NULL);
    assert(FocAdcTiming_Format("ADC SPREAD V",out,sizeof(out)));
    assert(strstr(out,"SUM=524544") != NULL);
    assert(!FocAdcTiming_Format("ADC SPREAD V",out,4));
    assert(FocAdcTiming_Format("ADC WINDOW",out,sizeof(out)));
    assert(strstr(out,"HW_VERIFIED=0"));
#if defined(FOC_ADC_RC_DIAGNOSTIC)
    assert(strstr(out,"RC_MIN=1700 LATE=1"));
#else
    assert(strstr(out,"RC_MIN=0 LATE=0"));
#endif
    assert(FocAdcTiming_Format("ADC BUFFER",out,sizeof(out)));
    assert(strstr(out,"DONE=2 DROP_B=0 DROP_S=0") != NULL);
    for (unsigned i=0; i<768; ++i) FocAdcTiming_RecordRaw(123,456);
    FocAdcTiming_Snapshot(&s);
    assert(s.pairs == 1280 && s.processed_blocks == 2 && s.buffers_ready == 2);
    assert(s.dropped_blocks == 1 && s.dropped_samples == 256 && s.blocks == 2);
    assert(FocAdcTiming_ProcessRawOne() && FocAdcTiming_ProcessRawOne());
    FocAdcTiming_Snapshot(&s);
    assert(s.blocks == 4 && s.processed_blocks == 4 && s.raw.sum[0] == 123 * 256);
    assert(s.raw.sum[1] == 456 * 256 && !s.mixed_block && !s.buffers_ready);
    for (unsigned i=0; i<256; ++i) FocAdcTiming_RecordRaw(4095,4095);
    assert(FocAdcTiming_ProcessRawOne());
    FocAdcTiming_Snapshot(&s);
    assert(s.blocks == 6 && s.raw.sum_sq[0] == 4292870400U); /* Capture 5 was dropped. */
    FocAdcTiming_NoteWorkerStack(1700);
    assert(FocAdcTiming_Format("ADC BUFFER",out,sizeof(out)));
    assert(strstr(out,"DROP_B=1 DROP_S=256") && strstr(out,"STK_VALID=1 FREE_B=1700"));
    assert(!FocAdcTiming_Format("ADC BUFFER",out,4));
    /* ProtocolTask has a 192-byte response buffer. Largest 32-bit counters
     * must still fit; formatting never silently reports truncated success. */
    int worst = snprintf(out,sizeof(out),
        "OK ADC BUFFER N=256 READY=2 BUSY=1 DONE=%lu DROP_B=%lu DROP_S=%lu REJECT=%lu MAX_CYC=%lu STK_VALID=1 FREE_B=%lu",
        (unsigned long)UINT32_MAX,(unsigned long)UINT32_MAX,(unsigned long)UINT32_MAX,
        (unsigned long)UINT32_MAX,(unsigned long)UINT32_MAX,(unsigned long)UINT32_MAX);
    assert(worst > 0 && (unsigned)worst < sizeof(out));
    start = FocAdcTiming_IrqEnter();
    mock_dwt.CYCCNT += 9000;
    FocAdcTiming_IrqExit(start);
    FocAdcTiming_Snapshot(&s);
    assert(s.deadline_misses == 1);
    mock_dwt.CTRL = 0;
    start = FocAdcTiming_IrqEnter();
    mock_dwt.CYCCNT += 99999;
    FocAdcTiming_IrqExit(start);
    FocAdcTiming_Snapshot(&s);
    assert(!s.dwt_on && s.max_cycles == 9000);
    puts("PASS: actual STM32 adapter against mock registers, masks/UG/pairs/DWT-wrap/spread/format");
    return 0;
#endif
}
