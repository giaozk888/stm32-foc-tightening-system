/* Reuse HAL mocks, but exercise the actual adapter in PA1-only mode. */
#define ADC_DMA_PA1_ONLY_DIAGNOSTIC 1
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
    if (scenario >= 101 && scenario <= 106) fail_call = scenario - 100;
    if (scenario >= 207 && scenario <= 213) fail_call = scenario - 200;
    if (scenario == 1) sampling_corrupt_index = 1;
    if (scenario == 2) w_adc.Instance->CR = ADC_CR_ADSTART;
    const int ok = AdcDmaDiag_Start(10U);
    if (scenario == 1 || scenario == 2 || (scenario >= 101 && scenario <= 106)) {
        assert(!ok && !(mock_tim.CR1 & TIM_CR1_CEN));
        AdcDmaDiag_Service(11U); assert(result.state == ADC_DMA_DIAG_FAILED);
        assert(!AdcDmaDiag_Start(12U)); return 0;
    }
    assert(ok && result.sampling_checked_mask == 2U && configured_mask == 2U);
    assert(!destinations[0] && destinations[1] && !destinations[2]);
    assert(!(u.Instance->CR & (ADC_CR_ADSTART | ADC_CR_JADSTART)));
    assert(!(w_adc.Instance->CR & (ADC_CR_ADSTART | ADC_CR_JADSTART)));
    for (unsigned i = 0U; i < 4096U; ++i) destinations[1][i] = (uint16_t)(2000U + i % 100U);
    uint16_t a, b, c; assert(!AdcDmaDiag_ReadThreePhase(0,&a,&b,&c));
    if (scenario == 3) AdcDmaDiag_Service(1010U);
    else if (scenario == 4) { w_adc.Instance->CR = ADC_CR_ADSTART; AdcDmaDiag_Service(11U); }
    else if (scenario == 5) { mock_dma[1].CNDTR = 1U; in_irq=1; AdcDmaDiag_Complete(&v); in_irq=0; }
    else if (scenario == 6) { v.ErrorCode = HAL_ADC_ERROR_OVR; AdcDmaDiag_Error(&v); }
    else if (scenario == 7) { locked=0; Complete(1U); }
    else if (scenario == 8) { Complete(0U); }
    else {
        if (scenario == 9) destinations[1][99] = 4096U;
        if (scenario == 10) v.Instance->ISR = ADC_FLAG_OVR;
        Complete(1U);
    }
    AdcDmaDiag_Service(215U);
    assert(!(mock_tim.CR1 & TIM_CR1_CEN) && !mock_tim.CCER && !mock_tim.BDTR);
    for (unsigned i = 0U; i < 3U; ++i) assert(!(mock_dma[i].CCR & DMA_CCR_EN));
    if (scenario == 0) {
        assert(result.state == ADC_DMA_DIAG_READY && result.restored);
        assert(result.count_u == 0U && result.count_v == 4096U && result.count_w == 0U);
        assert(result.irq_u == 0U && result.irq_v == 1U && result.irq_w == 0U);
        assert(AdcDmaDiag_ReadThreePhase(99,&a,&b,&c) && a == 0U && b == 2099U && c == 0U);
        assert(!AdcDmaDiag_ReadThreePhase(4096,&a,&b,&c));
        assert(u.Instance->SQR1 == 18U && v.Instance->SQR1 == 11U);
        assert(u.Instance->SMPR1 == 111U && v.Instance->SMPR1 == 222U);
    } else assert(result.state == ADC_DMA_DIAG_FAILED);
    assert(!AdcDmaDiag_Start(216U)); return 0;
}
