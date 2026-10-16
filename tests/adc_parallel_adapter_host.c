/* Run the actual parallel adapter against HAL/register mocks, not an
 * electrical or timing simulation. Every scenario runs in a fresh process. */
#define ADC_DMA_PARALLEL_DIAGNOSTIC 1
#define ADC_DMA_THREE_PHASE_DIAGNOSTIC 1
#define ADC_DMA_RAW_DIAGNOSTIC 1
#define ZERO_RETEST_BOOT 1
#define FOC_ADC_CLOCK_STM32_H
#include "main.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
TIM_TypeDef mock_tim;
GPIO_TypeDef mock_gpio;
ADC_TypeDef mock_adc[3];
ADC_Common_TypeDef mock_common, mock_common345;
DMA_Channel_TypeDef mock_dma[3];
uint32_t mock_clock345;
static int clock_ok = 1, locked = 1, calls, fail_call, in_irq;
static int sampling_corrupt_index = -1;
static uint16_t *destinations[3];
static int FocAdcClock_IsExpected(void) { return clock_ok; }
static uint8_t Locked(void) { return (uint8_t)(locked && !mock_gpio.ODR && !mock_tim.CCER &&
    !(mock_tim.BDTR & (TIM_BDTR_MOE | TIM_BDTR_AOE))); }
#include "../firmware_common/adc_parallel_diag.c"
static HAL_StatusTypeDef Step(void) { assert(!in_irq); return ++calls == fail_call ? HAL_ERROR : HAL_OK; }
HAL_StatusTypeDef HAL_RCCEx_PeriphCLKConfig(RCC_PeriphCLKInitTypeDef *c)
{ assert(c->PeriphClockSelection == RCC_PERIPHCLK_ADC345); mock_clock345 = c->Adc345ClockSelection; return Step(); }
void HAL_GPIO_Init(GPIO_TypeDef *g, GPIO_InitTypeDef *c)
{ assert(g == GPIOA && c->Pin == GPIO_PIN_8 && c->Mode == GPIO_MODE_ANALOG && !c->Pull); }
HAL_StatusTypeDef HAL_ADC_Init(ADC_HandleTypeDef *a)
{ if (a->Instance == ADC5) mock_common345.CCR = a->Init.ClockPrescaler; return Step(); }
HAL_StatusTypeDef HAL_ADCEx_Calibration_Start(ADC_HandleTypeDef *a, uint32_t mode)
{ assert(a->Instance == ADC5 && mode == ADC_SINGLE_ENDED && !(mock_tim.CR1 & TIM_CR1_CEN)); return Step(); }
HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef *a, const ADC_ChannelConfTypeDef *c)
{
    assert(a->Init.NbrOfConversion == 1U && a->Init.ScanConvMode == ADC_SCAN_DISABLE);
    assert(c->Rank == ADC_REGULAR_RANK_1);
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
    assert(c->SamplingTime == ADC_SAMPLETIME_247CYCLES_5);
#else
    assert(c->SamplingTime == ADC_SAMPLETIME_12CYCLES_5);
#endif
    assert(c->Channel == (a->Instance == ADC2 ? ADC_CHANNEL_2 : ADC_CHANNEL_1));
    a->Instance->SQR1 = c->Channel; a->Instance->SMPR1 = c->SamplingTime; return Step();
}
HAL_StatusTypeDef HAL_DMA_Init(DMA_HandleTypeDef *d)
{ d->Instance->CCR = 0U; return Step(); }
HAL_StatusTypeDef HAL_ADC_Start_DMA(ADC_HandleTypeDef *a, uint32_t *p, uint32_t n)
{
    assert(!(mock_tim.CR1 & TIM_CR1_CEN) && Locked());
    assert(a->Init.ExternalTrigConv == ADC_EXTERNALTRIG_T1_TRGO2 && a->Init.DMAContinuousRequests);
    assert(a->DMA_Handle->Init.Mode == DMA_NORMAL && n == ADC_DMA_DIAG_PAIRS);
    if (Step() != HAL_OK) return HAL_ERROR;
    unsigned i = a->Instance == ADC1 ? 0U : (a->Instance == ADC2 ? 1U : 2U);
    if ((int)i == sampling_corrupt_index) a->Instance->SMPR1 = ADC_SAMPLETIME_12CYCLES_5;
    destinations[i] = (uint16_t *)p;
    a->DMA_Handle->Instance->CCR = DMA_CCR_EN | DMA_IT_HT | DMA_IT_TC | DMA_IT_TE;
    a->DMA_Handle->Instance->CNDTR = n; a->Instance->CR |= ADC_CR_ADSTART; return HAL_OK;
}
HAL_StatusTypeDef HAL_ADC_Stop_DMA(ADC_HandleTypeDef *a)
{ a->Instance->CR = 0U; a->DMA_Handle->Instance->CCR = 0U; return Step(); }
HAL_StatusTypeDef HAL_ADC_Stop(ADC_HandleTypeDef *a) { a->Instance->CR = 0U; return Step(); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStop(ADC_HandleTypeDef *a) { a->Instance->CR = 0U; return Step(); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStop_IT(ADC_HandleTypeDef *a) { return HAL_ADCEx_InjectedStop(a); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStart(ADC_HandleTypeDef *a) { a->Instance->CR |= ADC_CR_JADSTART; return Step(); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStart_IT(ADC_HandleTypeDef *a) { return HAL_ADCEx_InjectedStart(a); }
uint32_t HAL_ADC_GetError(ADC_HandleTypeDef *a) { return a->ErrorCode; }
void HAL_ADC_IRQHandler(ADC_HandleTypeDef *a) { (void)a; }
void HAL_DMA_IRQHandler(DMA_HandleTypeDef *d) { (void)d; }
void HAL_NVIC_SetPriority(unsigned a, unsigned b, unsigned c) { (void)a; (void)b; (void)c; }
void HAL_NVIC_ClearPendingIRQ(unsigned a) { (void)a; }
void HAL_NVIC_EnableIRQ(unsigned a) { (void)a; }
void HAL_NVIC_DisableIRQ(unsigned a) { (void)a; }
static void Complete(unsigned i)
{ mock_dma[i].CNDTR = 0U; in_irq = 1; AdcDmaDiag_Complete(adcs[i]); in_irq = 0; }
int main(int argc, char **argv)
{
    assert(argc == 2); int scenario = atoi(argv[1]);
    ADC_HandleTypeDef u = {0}, v = {0}; u.Instance = ADC1; v.Instance = ADC2;
    u.Init.ClockPrescaler = FOC_ADC_CLOCK_PRESCALER;
    u.Instance->SQR1 = 18U; v.Instance->SQR1 = 11U;
    u.Instance->SMPR1 = 111U; v.Instance->SMPR1 = 222U;
    mock_tim.ARR = 4249U; mock_tim.CCR4 = 3500U; mock_tim.CR2 = TIM_TRGO2_OC4REF;
    if (scenario >= 20 && scenario <= 22) fail_call = scenario - 19;
    AdcDmaDiag_Init(&u, &v, Locked);
    if (scenario >= 20 && scenario <= 22) { assert(!AdcDmaDiag_ParallelReady()); assert(!AdcDmaDiag_Start(0)); return 0; }
    assert(AdcDmaDiag_ParallelReady()); calls = fail_call = 0;
    if (scenario >= 101 && scenario <= 114) fail_call = scenario - 100;
    if (scenario >= 215 && scenario <= 221) fail_call = scenario - 200;
    if (scenario == 1) clock_ok = 0;
    if (scenario == 2) locked = 0;
    if (scenario == 3) mock_common.CCR = 1U;
    if (scenario == 4) mock_tim.ARR = 4248U;
    if (scenario == 5) mock_tim.CR1 = TIM_CR1_CEN;
    if (scenario == 6) mock_clock345 = 1U;
    if (scenario == 7) mock_common345.CCR = 0U;
    if (scenario == 8) mock_common345.CCR |= ADC_CCR_DUAL;
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
    if (scenario >= 40 && scenario <= 42) sampling_corrupt_index = scenario - 40;
#endif
    uint32_t start = scenario == 10 ? UINT32_MAX - 499U : 10U;
    int ok = AdcDmaDiag_Start(start);
    if (scenario >= 1 && scenario <= 8) { assert(!ok); return 0; }
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
    if (scenario >= 40 && scenario <= 42) {
        assert(!ok && !(mock_tim.CR1 & TIM_CR1_CEN));
        AdcDmaDiag_Service(start + 1U);
        assert(result.state == ADC_DMA_DIAG_FAILED && result.reason == ADC_DMA_DIAG_CONFIG);
        for (unsigned i=0; i<3; ++i) assert(!(mock_dma[i].CCR & DMA_CCR_EN));
        assert(!AdcDmaDiag_Start(start + 2U)); return 0;
    }
#endif
    if (scenario >= 101 && scenario <= 114) {
        assert(!ok); AdcDmaDiag_Service(start + 1U);
        assert(result.state == ADC_DMA_DIAG_FAILED && !AdcDmaDiag_Start(start + 2U));
        for (unsigned i=0; i<3; ++i) assert(!(mock_dma[i].CCR & DMA_CCR_EN));
        assert(!(mock_tim.CR1 & TIM_CR1_CEN)); return 0;
    }
    assert(ok && result.state == ADC_DMA_DIAG_RUNNING && !AdcDmaDiag_Start(start));
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
    assert(result.sampling_checked_mask == 7U);
#endif
    uint16_t a, b, c; assert(!AdcDmaDiag_ReadThreePhase(0, &a, &b, &c));
    for (unsigned i = 0U; i < 4096U; ++i) {
        destinations[0][i] = (uint16_t)(1500U + i % 101U);
        destinations[1][i] = (uint16_t)(1510U + i % 91U);
        destinations[2][i] = (uint16_t)(1600U + i % 73U);
    }
    destinations[0][99] = 0U; destinations[1][100] = 4095U; destinations[2][100] = 4095U;
    if (scenario == 9 || scenario == 10) AdcDmaDiag_Service(start + 1000U);
    else if (scenario == 11) { w_adc.ErrorCode = HAL_ADC_ERROR_OVR; in_irq=1; AdcDmaDiag_Error(&w_adc); in_irq=0; }
    else if (scenario == 12) { locked=0; Complete(0U); }
    else if (scenario == 13) { mock_dma[2].CNDTR = 1U; in_irq=1; AdcDmaDiag_Complete(&w_adc); in_irq=0; }
    else if (scenario == 14) { Complete(0U); Complete(0U); }
    else if (scenario == 15) { ADC_HandleTypeDef unknown={0}; in_irq=1; AdcDmaDiag_Complete(&unknown); in_irq=0; }
    else {
        if (scenario == 16) mock_adc[2].ISR = ADC_FLAG_OVR;
        if (scenario == 17) destinations[2][100] = 4096U;
        if (scenario == 18) { Complete(0U); Complete(1U); AdcDmaDiag_Service(start+1000U); }
        else {
            static const unsigned order[6][3]={{0,1,2},{0,2,1},{1,0,2},{1,2,0},{2,0,1},{2,1,0}};
            unsigned permutation = scenario >= 30 && scenario <= 35 ? (unsigned)(scenario-30) : 0U;
            for (unsigned j=0; j<3; ++j) {
                Complete(order[permutation][j]);
                if (j<2) { assert(result.state == ADC_DMA_DIAG_RUNNING); assert(!AdcDmaDiag_ReadThreePhase(0,&a,&b,&c)); }
            }
        }
    }
    AdcDmaDiag_Service(start + 205U);
    assert(!(mock_tim.CR1 & TIM_CR1_CEN) && !mock_tim.CCER && !mock_tim.BDTR);
    for (unsigned i=0; i<3; ++i) assert(!(mock_dma[i].CCR & DMA_CCR_EN));
    if (scenario >= 215 && scenario <= 221) { assert(result.state == ADC_DMA_DIAG_FAILED && result.reason == ADC_DMA_DIAG_STOP_ERROR); return 0; }
    assert(u.Instance->SQR1 == 18U && v.Instance->SQR1 == 11U && u.Instance->SMPR1 == 111U && v.Instance->SMPR1 == 222U);
    assert(!u.DMA_Handle && !v.DMA_Handle && !(w_adc.Instance->CR & (ADC_CR_ADSTART|ADC_CR_JADSTART)));
    if (scenario == 0 || (scenario >=30 && scenario<=35)) {
        assert(result.state == ADC_DMA_DIAG_READY && result.restored);
        assert(result.count_u==4096U && result.count_v==4096U && result.count_w==4096U);
        assert(result.irq_u==1U && result.irq_v==1U && result.irq_w==1U);
        assert(AdcDmaDiag_ReadThreePhase(100,&a,&b,&c) && b==4095U && c==4095U);
        assert(!AdcDmaDiag_ReadThreePhase(4096,&a,&b,&c));
        assert(!AdcDmaDiag_ReadThreePhase(0,&a,&b,NULL));
        assert(!AdcDmaDiag_Read(0,&a,&b));
    } else assert(result.state == ADC_DMA_DIAG_FAILED && !AdcDmaDiag_ReadThreePhase(0,&a,&b,&c));
    assert(!AdcDmaDiag_Start(start+206U)); puts("PARALLEL CAPTURE/CLEANUP PASS"); return 0;
}
