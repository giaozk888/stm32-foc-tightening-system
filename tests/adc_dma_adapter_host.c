/* Execute the ACTUAL adapter under a small HAL/register model. This is NOT a
 * timing/electrical simulation. Every case runs in a fresh OS process. */
#include "main.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define FOC_ADC_CLOCK_STM32_H
#define ZERO_RETEST_BOOT 1
#define ADC_DMA_RAW_DIAGNOSTIC 1
TIM_TypeDef mock_tim;
GPIO_TypeDef mock_gpio;
ADC_TypeDef mock_adc[2];
ADC_Common_TypeDef mock_common;
DMA_Channel_TypeDef mock_dma[2];
static int clock_ok = 1, locked = 1, fail_call, calls, in_irq;
static uint16_t *destinations[2];
static uint32_t destination_lengths[2];
static int FocAdcClock_IsExpected(void) { return clock_ok; }
static uint8_t Locked(void) { return (uint8_t)(locked && !mock_gpio.ODR && !mock_tim.CCER &&
    !(mock_tim.BDTR & (TIM_BDTR_MOE | TIM_BDTR_AOE))); }
#include "../firmware_common/adc_dma_diag.c"
static HAL_StatusTypeDef Step(void) { return ++calls == fail_call ? HAL_ERROR : HAL_OK; }
HAL_StatusTypeDef HAL_ADC_Init(ADC_HandleTypeDef *a) { (void)a; return Step(); }
HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef *a, const ADC_ChannelConfTypeDef *c)
{
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    if (c->Rank == ADC_REGULAR_RANK_2) {
        assert(a->Instance == ADC1 && c->Channel == ADC_CHANNEL_9);
        assert(a->Init.ScanConvMode == ADC_SCAN_ENABLE && a->Init.NbrOfConversion == 2U);
        a->Instance->SQR2 = c->Channel;
    } else
#endif
        a->Instance->SQR1 = c->Channel;
    a->Instance->SMPR1 = c->SamplingTime;
    return Step();
}
HAL_StatusTypeDef HAL_DMA_Init(DMA_HandleTypeDef *d) { d->Instance->CCR = 0U; return Step(); }
HAL_StatusTypeDef HAL_ADC_Start_DMA(ADC_HandleTypeDef *a, uint32_t *p, uint32_t n)
{
    assert(!(mock_tim.CR1 & TIM_CR1_CEN));
    assert(a->Init.ExternalTrigConv == ADC_EXTERNALTRIG_T1_TRGO2);
    assert(a->Init.DMAContinuousRequests == ENABLE);
    assert(a->DMA_Handle->Init.Mode == DMA_NORMAL);
    if (Step() != HAL_OK) return HAL_ERROR;
    unsigned i = a->Instance == ADC1 ? 0U : 1U;
    destinations[i] = (uint16_t *)p;
    destination_lengths[i] = n;
    assert(n == ADC_DMA_DIAG_PAIRS * (i == 0U ? ADC_DMA_DIAG_U_STRIDE : 1U));
    a->DMA_Handle->Instance->CNDTR = n;
    a->DMA_Handle->Instance->CCR = DMA_CCR_EN | DMA_IT_HT | DMA_IT_TC | DMA_IT_TE;
    a->Instance->CR |= ADC_CR_ADSTART;
    return HAL_OK;
}
HAL_StatusTypeDef HAL_ADC_Stop_DMA(ADC_HandleTypeDef *a)
{
    assert(!in_irq);
    a->Instance->CR = 0U;
    a->DMA_Handle->Instance->CCR = 0U;
    return Step();
}
HAL_StatusTypeDef HAL_ADC_Stop(ADC_HandleTypeDef *a) { assert(!in_irq); a->Instance->CR = 0U; return Step(); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStop(ADC_HandleTypeDef *a) { a->Instance->CR = 0U; return Step(); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStop_IT(ADC_HandleTypeDef *a) { return HAL_ADCEx_InjectedStop(a); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStart(ADC_HandleTypeDef *a) { a->Instance->CR |= ADC_CR_JADSTART; return Step(); }
HAL_StatusTypeDef HAL_ADCEx_InjectedStart_IT(ADC_HandleTypeDef *a) { return HAL_ADCEx_InjectedStart(a); }
uint32_t HAL_ADC_GetError(ADC_HandleTypeDef *a) { return a->ErrorCode; }
void HAL_DMA_IRQHandler(DMA_HandleTypeDef *d) { (void)d; }
void HAL_NVIC_SetPriority(unsigned a, unsigned b, unsigned c) { (void)a; (void)b; (void)c; }
void HAL_NVIC_ClearPendingIRQ(unsigned a) { (void)a; }
void HAL_NVIC_EnableIRQ(unsigned a) { (void)a; }
void HAL_NVIC_DisableIRQ(unsigned a) { (void)a; }
static void Fill(void)
{
    for (unsigned i = 0; i < ADC_DMA_DIAG_PAIRS; ++i) {
        destinations[0][i * ADC_DMA_DIAG_U_STRIDE] = (uint16_t)(1500U + i % 101U);
        destinations[1][i] = (uint16_t)(1510U + i % 91U);
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        destinations[0][i * 2U + 1U] = (uint16_t)(1600U + i % 73U);
#endif
    }
    destinations[0][99U * ADC_DMA_DIAG_U_STRIDE] = 0U; /* Retain abnormal raw data. */
    destinations[1][100] = 4095U;
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    destinations[0][201U] = 4095U;
#endif
}
static void Complete(unsigned i)
{
    mock_dma[i].CNDTR = 0U;
    in_irq = 1;
    AdcDmaDiag_Complete(adcs[i]);
    in_irq = 0;
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    int scenario = atoi(argv[1]);
    ADC_HandleTypeDef u = {0}, v = {0};
    u.Instance = ADC1; v.Instance = ADC2;
    u.Instance->SQR1 = 18U; v.Instance->SQR1 = 11U;
    u.Instance->SMPR1 = 111U; v.Instance->SMPR1 = 222U;
    mock_tim.ARR = 4249U; mock_tim.CCR4 = 3500U; mock_tim.CR2 = TIM_TRGO2_OC4REF;
    AdcDmaDiag_Init(&u, &v, Locked);
    uint16_t a, b;
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    uint16_t w;
    assert(!AdcDmaDiag_ReadThreePhase(0U, &a, &b, &w));
#endif
    assert(!AdcDmaDiag_Read(0U, &a, &b));
    if (scenario >= 100 && scenario < 200) fail_call = scenario - 100;
    if (scenario >= 200) fail_call = scenario - 200;
    if (scenario == 1) clock_ok = 0;
    if (scenario == 2) locked = 0;
    if (scenario == 3) mock_common.CCR = 1U;
    if (scenario == 4) mock_tim.ARR = 4248U;
    if (scenario == 5) mock_tim.CR1 = TIM_CR1_CEN;
    uint32_t start = scenario == 9 ? UINT32_MAX - 499U : 10U;
    int ok = AdcDmaDiag_Start(start);
    if (scenario >= 1 && scenario <= 5) { assert(!ok); puts("ADMISSION PASS"); return 0; }
    if (scenario >= 100 && scenario < 200) {
        assert(!ok);
        assert(!(mock_tim.CR1 & TIM_CR1_CEN));
        AdcDmaDiag_Service(start + 1U);
        assert(result.state == ADC_DMA_DIAG_FAILED);
        assert(!AdcDmaDiag_Start(start + 2U));
        assert(!(mock_dma[0].CCR & DMA_CCR_EN) && !(mock_dma[1].CCR & DMA_CCR_EN));
        puts("PARTIAL SETUP CLEANUP PASS"); return 0;
    }
    assert(ok && result.state == ADC_DMA_DIAG_RUNNING && (mock_tim.CR1 & TIM_CR1_CEN));
    assert(!AdcDmaDiag_Start(start));
    assert(!AdcDmaDiag_Read(0U, &a, &b));
    Fill();
    assert(destination_lengths[0] == ADC_DMA_DIAG_PAIRS * ADC_DMA_DIAG_U_STRIDE);
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    if (scenario == 14) destinations[0][201U] = 4096U;
#endif
    if (scenario == 6) {
        u.ErrorCode = HAL_ADC_ERROR_OVR;
        in_irq = 1; AdcDmaDiag_Error(&u); in_irq = 0;
    } else if (scenario == 7 || scenario == 9) {
        AdcDmaDiag_Service(start + ADC_DMA_DIAG_TIMEOUT_MS);
    } else if (scenario == 8) {
        locked = 0; Complete(0U);
    } else if (scenario == 15) {
        mock_dma[0].CNDTR = 1U; /* Last W value is missing: never publish READY. */
        mock_dma[1].CNDTR = 0U;
        in_irq = 1; AdcDmaDiag_Complete(&u); in_irq = 0;
    } else {
        Complete(scenario == 10 ? 1U : 0U);
        assert(result.state == ADC_DMA_DIAG_RUNNING);
        assert(!AdcDmaDiag_Read(0U, &a, &b));
        if (scenario == 11) mock_adc[1].ISR |= ADC_FLAG_OVR;
        if (scenario == 13) { in_irq = 1; AdcDmaDiag_Complete(&u); in_irq = 0; }
        if (scenario == 12) { in_irq = 1; AdcDmaDiag_Complete(&v); in_irq = 0; }
        else Complete(scenario == 10 ? 0U : 1U);
    }
    AdcDmaDiag_Service(start + 205U);
    assert(!(mock_tim.CR1 & TIM_CR1_CEN) && !mock_tim.CCER && !mock_tim.BDTR);
    assert(!(mock_dma[0].CCR & DMA_CCR_EN) && !(mock_dma[1].CCR & DMA_CCR_EN));
    if (scenario >= 200) {
        assert(result.state == ADC_DMA_DIAG_FAILED && result.reason == ADC_DMA_DIAG_STOP_ERROR);
        assert(!AdcDmaDiag_Read(0U, &a, &b));
        assert(!AdcDmaDiag_Start(start + 206U));
        puts("RESTORE FAILURE CLOSED PASS"); return 0;
    }
    assert(u.Init.ExternalTrigConv == 0U && v.Init.ExternalTrigConv == 0U);
    assert(u.Instance->SQR1 == 18U && v.Instance->SQR1 == 11U);
    assert(u.Instance->SMPR1 == 111U && v.Instance->SMPR1 == 222U);
    assert(!u.DMA_Handle && !v.DMA_Handle);
    assert((u.Instance->CR & ADC_CR_JADSTART) && (v.Instance->CR & ADC_CR_JADSTART));
    if (scenario == 0 || scenario == 10) {
        assert(result.state == ADC_DMA_DIAG_READY && result.restored == 1U);
        assert(result.count_u == 4096U && result.count_v == 4096U);
        assert(result.min_u == 0U && result.max_v == 4095U);
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        assert(result.count_w == 4096U && result.min_w == 1600U && result.max_w == 4095U);
        assert(!AdcDmaDiag_Read(99U, &a, &b));
        assert(AdcDmaDiag_ReadThreePhase(99U, &a, &b, &w) && a == 0U && w == 1626U);
        assert(AdcDmaDiag_ReadThreePhase(100U, &a, &b, &w) && b == 4095U && w == 4095U);
        assert(!AdcDmaDiag_ReadThreePhase(4096U, &a, &b, &w));
        assert(!AdcDmaDiag_ReadThreePhase(0U, &a, &b, NULL));
        assert(u.Instance->SQR2 == 0U);
#else
        assert(AdcDmaDiag_Read(99U, &a, &b) && a == 0U);
#endif
        assert(!AdcDmaDiag_Read(4096U, &a, &b));
        assert(!AdcDmaDiag_Read(0U, NULL, &b));
        puts("CAPTURE/OWNERSHIP/RESTORE PASS");
    } else {
        assert(result.state == ADC_DMA_DIAG_FAILED);
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        if (scenario == 15) assert(result.count_u == 4096U && result.count_w == 4095U);
        assert(!AdcDmaDiag_ReadThreePhase(0U, &a, &b, &w));
#endif
        assert(!AdcDmaDiag_Read(0U, &a, &b));
        puts("ERROR/TIMEOUT/LOCK PASS");
    }
    return 0;
}
