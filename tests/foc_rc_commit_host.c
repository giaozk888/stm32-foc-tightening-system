/* Actual timing adapter linked against register mocks, no hardware I/O. */
#include "main.h"
#include "foc_adc_timing_stm32.h"
#include "foc_adc_clock_stm32.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
TIM_TypeDef mock_tim;
ADC_TypeDef mock_adc1, mock_adc2;
DWT_Type mock_dwt;
uint32_t mock_primask, mock_ipsr;
uint32_t mock_hclk = 170000000, mock_sysclk = 170000000;
uint32_t mock_adc_clock_source = RCC_ADC12CLKSOURCE_SYSCLK;
ADC_Common_TypeDef mock_adc_common;
RCC_TypeDef mock_rcc;
uint32_t mock_frequency_reads;

int main(int argc, char **argv)
{
    unsigned which = argc == 2 ? (unsigned)strtoul(argv[1], NULL, 10) : 0;
    assert(which <= 13);
    mock_tim.ARR = FOC_ADC_TIMER_ARR;
    mock_tim.BDTR = 85;
    mock_tim.CR1 = TIM_COUNTERMODE_CENTERALIGNED1;
    mock_tim.CCMR1 = TIM_CCMR1_OC1PE | TIM_CCMR1_OC2PE;
    mock_tim.CCMR2 = TIM_CCMR2_OC3PE | TIM_CCMR2_OC4PE;
    mock_tim.CR2 = TIM_TRGO2_OC4REF;
    mock_adc_common.CCR = FOC_ADC_CLOCK_PRESCALER;
    assert(!FocAdcTiming_RcActuationReady());
    assert(FocAdcTiming_Commit(.5f,.5f,.5f) == FOC_WINDOW_OK);
    assert(mock_tim.CCR4 == 4184);
    assert(FocAdcTiming_CertifyClock());
    mock_tim.CR1 |= TIM_CR1_CEN | TIM_CR1_DIR;
    mock_tim.CNT = 4200;
    mock_dwt.CTRL = DWT_CTRL_CYCCNTENA_Msk;
    mock_dwt.CYCCNT = 1000;
    uint32_t start = FocAdcTiming_IrqEnter();
    mock_dwt.CYCCNT += 50;
    FocAdcTiming_IrqExit(start);
    for (unsigned i = 0; i < 1000; ++i) FocAdcTiming_RecordRaw(1560, 1560);
    assert(FocAdcTiming_RcActuationReady());
    FocWindowPlan plan;
    assert(FocAdcTiming_Prepare(.52f,.5f,.48f,&plan) == FOC_WINDOW_OK);
    start = FocAdcTiming_IrqEnter();
    mock_ipsr = 34;
    mock_dwt.CYCCNT += 100;
    mock_tim.CNT = 4100;
    uint32_t ccr[4] = {mock_tim.CCR1,mock_tim.CCR2,mock_tim.CCR3,mock_tim.CCR4};
    int success = which == 0 || which == 1 || which == 10;
    if (which == 1) mock_primask = 1;
    if (which == 2) mock_dwt.CTRL = 0;
    if (which == 3) mock_ipsr = 0;
    if (which == 4) mock_tim.CR1 |= TIM_CR1_UDIS;
    if (which == 5) mock_tim.CR1 &= ~TIM_CR1_DIR;
    if (which == 6) mock_tim.CNT = FOC_ADC_COMMIT_GUARD_TICKS;
    if (which == 7) mock_dwt.CYCCNT = start + 4200 - FOC_ADC_COMMIT_GUARD_TICKS;
    if (which == 8) mock_dwt.CYCCNT = start + 8500; /* A new cycle must not pass. */
    if (which == 9) FocAdcTiming_IrqExit(start);
    if (which == 10) {
        mock_dwt.CYCCNT = UINT32_MAX - 30;
        start = FocAdcTiming_IrqEnter();
        mock_dwt.CYCCNT = 69; /* 100 cycles, modular wrap. */
    }
    if (which == 11) mock_tim.CR1 &= ~TIM_CR1_CEN;
    if (which == 13) {
        mock_dwt.CYCCNT = start + 9000;
        FocAdcTiming_IrqExit(start); /* A coarse alarm latches admission closed. */
        start = FocAdcTiming_IrqEnter();
        mock_dwt.CYCCNT = start + 50;
        assert(!FocAdcTiming_RcActuationReady());
    }
    uint32_t mask = mock_primask, cr1 = mock_tim.CR1;
    assert(FocAdcTiming_CommitBeforeBottom(which == 12 ? NULL : &plan) == success);
    assert(mock_primask == mask && mock_tim.CR1 == cr1);
    if (success) {
        assert(mock_tim.CCR1 == plan.phase[0] && mock_tim.CCR2 == plan.phase[1]);
        assert(mock_tim.CCR3 == plan.phase[2] && mock_tim.CCR4 == plan.trigger);
    } else {
        assert(mock_tim.CCR1 == ccr[0] && mock_tim.CCR2 == ccr[1]);
        assert(mock_tim.CCR3 == ccr[2] && mock_tim.CCR4 == ccr[3]);
        assert(!FocAdcTiming_RcActuationReady());
        mock_ipsr = 34; mock_dwt.CTRL = 1;
        mock_tim.CR1 = TIM_COUNTERMODE_CENTERALIGNED1 | TIM_CR1_CEN | TIM_CR1_DIR;
        mock_tim.CNT = 4100;
        start = FocAdcTiming_IrqEnter(); mock_dwt.CYCCNT = start + 50;
        assert(!FocAdcTiming_CommitBeforeBottom(&plan)); /* No clear/retry API. */
    }
    char out[192];
    assert(FocAdcTiming_Format("ADC COMMIT",out,sizeof out));
    assert(strstr(out,"RC=1") && strstr(out,"GUARD=170 HW_VERIFIED=0"));
    assert(!FocAdcTiming_Format("ADC COMMIT",out,4));
    printf("PASS RC commit case %u: deadline/phase/masks/no-write rejection\n",which);
    return 0;
}
