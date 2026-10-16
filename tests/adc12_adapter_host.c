/* Actual locked adapter, with only same-group ADC1/2 conversions enabled. */
#define ADC_DMA_ADC12_ONLY_DIAGNOSTIC 1
#define ADC_DMA_PARALLEL_LONG_SAMPLE 1
#define main unused_parallel_main
#include "adc_parallel_adapter_host.c"
#undef main

int main(int argc, char **argv)
{
    assert(argc == 2);
    const int scenario = atoi(argv[1]);
    ADC_HandleTypeDef u = {0}, v = {0}; u.Instance = ADC1; v.Instance = ADC2;
    u.Init.ClockPrescaler = FOC_ADC_CLOCK_PRESCALER;
    u.Instance->SQR1 = 18U; v.Instance->SQR1 = 11U;
    u.Instance->SMPR1 = 111U; v.Instance->SMPR1 = 222U;
    mock_tim.ARR = 4249U; mock_tim.CCR4 = 3500U; mock_tim.CR2 = TIM_TRGO2_OC4REF;
    AdcDmaDiag_Init(&u, &v, Locked); assert(AdcDmaDiag_ParallelReady());
    calls = 0;
    if (scenario >= 101 && scenario <= 110) fail_call = scenario - 100;
    if (scenario >= 211 && scenario <= 218) fail_call = scenario - 200;
    if (scenario == 1 || scenario == 2) sampling_corrupt_index = scenario - 1;
    if (scenario == 3) w_adc.Instance->CR = ADC_CR_ADSTART;
    if (scenario == 4) w_adc.Instance->CR = ADC_CR_JADSTART;
    const int ok = AdcDmaDiag_Start(10U);
    if ((scenario >= 1 && scenario <= 4) || (scenario >= 101 && scenario <= 110)) {
        assert(!ok && !(mock_tim.CR1 & TIM_CR1_CEN));
        AdcDmaDiag_Service(11U); assert(result.state == ADC_DMA_DIAG_FAILED);
        for (unsigned i=0U; i<3U; ++i) assert(!(mock_dma[i].CCR & DMA_CCR_EN));
        assert(!AdcDmaDiag_Start(12U)); return 0;
    }
    assert(ok && result.sampling_checked_mask == 3U && configured_mask == 3U);
    assert(destinations[0] && destinations[1] && !destinations[2]);
    assert(!(w_adc.Instance->CR & (ADC_CR_ADSTART | ADC_CR_JADSTART)));
    assert(!AdcDmaDiag_Start(10U));
    for (unsigned i=0U; i<ADC_DMA_DIAG_PAIRS; ++i) {
        destinations[0][i] = (uint16_t)(1000U + i % 101U);
        destinations[1][i] = (uint16_t)(2000U + i % 100U);
    }
    uint16_t a, b, c; assert(!AdcDmaDiag_ReadThreePhase(0,&a,&b,&c));
    if (scenario == 5) AdcDmaDiag_Service(1010U);
    else if (scenario == 6 || scenario == 7) {
        w_adc.Instance->CR = scenario == 6 ? ADC_CR_ADSTART : ADC_CR_JADSTART;
        AdcDmaDiag_Service(11U);
    } else if (scenario == 8 || scenario == 9) {
        const unsigned i = (unsigned)(scenario - 8);
        mock_dma[i].CNDTR = 1U; in_irq=1; AdcDmaDiag_Complete(adcs[i]); in_irq=0;
    } else if (scenario == 10) { v.ErrorCode = HAL_ADC_ERROR_OVR; AdcDmaDiag_Error(&v); }
    else if (scenario == 11) { locked=0; Complete(1U); }
    else if (scenario == 12) Complete(2U);
    else if (scenario == 13) { Complete(0U); Complete(0U); }
    else if (scenario == 14) { Complete(0U); AdcDmaDiag_Service(1010U); }
    else if (scenario == 15) { Complete(0U); w_adc.Instance->CR=ADC_CR_ADSTART; Complete(1U); }
    else {
        if (scenario == 16 || scenario == 17) destinations[scenario-16][99] = 4096U;
        if (scenario == 18 || scenario == 19) adcs[scenario-18]->Instance->ISR = ADC_FLAG_OVR;
        const unsigned first = scenario == 20 ? 1U : 0U;
        Complete(first);
        assert(result.state == ADC_DMA_DIAG_RUNNING && (mock_tim.CR1 & TIM_CR1_CEN));
        assert(!AdcDmaDiag_ReadThreePhase(0,&a,&b,&c));
        Complete(1U-first);
    }
    AdcDmaDiag_Service(215U);
    assert(!(mock_tim.CR1 & TIM_CR1_CEN) && !mock_tim.CCER && !mock_tim.BDTR);
    for (unsigned i=0U; i<3U; ++i) assert(!(mock_dma[i].CCR & DMA_CCR_EN));
    assert(!(w_adc.Instance->CR & (ADC_CR_ADSTART|ADC_CR_JADSTART)));
    if (scenario == 0 || scenario == 20) {
        assert(result.state == ADC_DMA_DIAG_READY && result.restored);
        assert(result.count_u == ADC_DMA_DIAG_PAIRS && result.count_v == ADC_DMA_DIAG_PAIRS && result.count_w == 0U);
        assert(result.irq_u == 1U && result.irq_v == 1U && result.irq_w == 0U);
        assert(AdcDmaDiag_ReadThreePhase(99,&a,&b,&c) && a == 1099U && b == 2099U && c == 0U);
        assert(AdcDmaDiag_ReadThreePhase(ADC_DMA_DIAG_PAIRS-1U,&a,&b,&c));
        assert(a == 1000U + (ADC_DMA_DIAG_PAIRS-1U)%101U &&
               b == 2000U + (ADC_DMA_DIAG_PAIRS-1U)%100U && c == 0U);
        assert(!AdcDmaDiag_ReadThreePhase(ADC_DMA_DIAG_PAIRS,&a,&b,&c));
        assert(!AdcDmaDiag_ReadThreePhase(0,&a,&b,NULL));
        assert(u.Instance->SQR1 == 18U && v.Instance->SQR1 == 11U);
        assert(u.Instance->SMPR1 == 111U && v.Instance->SMPR1 == 222U);
    } else assert(result.state == ADC_DMA_DIAG_FAILED && !AdcDmaDiag_ReadThreePhase(0,&a,&b,&c));
    assert(!AdcDmaDiag_Start(216U)); return 0;
}
