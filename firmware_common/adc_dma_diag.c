#include "adc_dma_diag.h"
#include "foc_adc_clock_stm32.h"
#include "adc_raw_report.h"
#include <string.h>

#if !defined(ZERO_RETEST_BOOT) || !defined(ADC_DMA_RAW_DIAGNOSTIC)
#error "ADC DMA diagnostic is restricted to the hard-off standalone service"
#endif
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC) && !defined(ADC_DMA_RAW_DIAGNOSTIC)
#error "Three-phase acquisition requires the locked raw diagnostic"
#endif

static ADC_HandleTypeDef *adcs[2];
static DMA_HandleTypeDef dma[2];
static ADC_InitTypeDef saved_init[2];
static DMA_HandleTypeDef *saved_dma[2];
static uint32_t saved_sqr[2][4], saved_smpr[2][2];
static uint16_t raw_u[ADC_DMA_DIAG_PAIRS * ADC_DMA_DIAG_U_STRIDE] __attribute__((aligned(4)));
static uint16_t raw_v[ADC_DMA_DIAG_PAIRS] __attribute__((aligned(4)));
static volatile AdcDmaDiagStatus result;
static uint8_t (*is_locked)(void);
static uint32_t started_ms;
static volatile uint8_t done_mask;
static uint8_t attempted, configured;

static void StopTrigger(void)
{
    TIM1->CR1 &= ~TIM_CR1_CEN;
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    __DSB();
}

static void Fail(uint32_t reason)
{
    StopTrigger();
    if (result.reason == ADC_DMA_DIAG_OK) result.reason = reason;
    result.state = ADC_DMA_DIAG_STOPPING;
}

int AdcDmaDiag_Busy(void)
{
    return result.state == ADC_DMA_DIAG_ARMING || result.state == ADC_DMA_DIAG_RUNNING ||
           result.state == ADC_DMA_DIAG_STOPPING;
}

void AdcDmaDiag_Init(ADC_HandleTypeDef *u, ADC_HandleTypeDef *v,
                     uint8_t (*locked)(void))
{
    adcs[0] = u;
    adcs[1] = v;
    is_locked = locked;
}

static HAL_StatusTypeDef Configure(unsigned i)
{
    ADC_HandleTypeDef *adc = adcs[i];
    ADC_ChannelConfTypeDef channel = {0};
    adc->Init.ScanConvMode = ADC_SCAN_DISABLE;
    adc->Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    adc->Init.LowPowerAutoWait = DISABLE;
    adc->Init.ContinuousConvMode = DISABLE;
    adc->Init.NbrOfConversion = 1U;
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    if (i == 0U) {
        adc->Init.ScanConvMode = ADC_SCAN_ENABLE;
        adc->Init.NbrOfConversion = 2U;
    }
#endif
    adc->Init.DiscontinuousConvMode = DISABLE;
    adc->Init.ExternalTrigConv = ADC_EXTERNALTRIG_T1_TRGO2;
    adc->Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
    /* Unlimited ADC requests, finite NORMAL DMA. Timer is stopped at completion. */
    adc->Init.DMAContinuousRequests = ENABLE;
    adc->Init.Overrun = ADC_OVR_DATA_PRESERVED;
    adc->Init.OversamplingMode = DISABLE;
    if (HAL_ADC_Init(adc) != HAL_OK) return HAL_ERROR;
    channel.Channel = i == 0U ? ADC_CHANNEL_1 : ADC_CHANNEL_2;
    channel.Rank = ADC_REGULAR_RANK_1;
    channel.SamplingTime = ADC_SAMPLETIME_12CYCLES_5;
    channel.SingleDiff = ADC_SINGLE_ENDED;
    channel.OffsetNumber = ADC_OFFSET_NONE;
    if (HAL_ADC_ConfigChannel(adc, &channel) != HAL_OK) return HAL_ERROR;
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    if (i == 0U) {
        /* PC3 is already configured analog/no-pull by ADC1 MSP.
         * W follows U in the SAME sequence; no claim of simultaneous U/W. */
        channel.Channel = ADC_CHANNEL_9;
        channel.Rank = ADC_REGULAR_RANK_2;
        if (HAL_ADC_ConfigChannel(adc, &channel) != HAL_OK) return HAL_ERROR;
    }
#endif
    dma[i].Instance = i == 0U ? DMA1_Channel3 : DMA1_Channel4;
    dma[i].Init.Request = i == 0U ? DMA_REQUEST_ADC1 : DMA_REQUEST_ADC2;
    dma[i].Init.Direction = DMA_PERIPH_TO_MEMORY;
    dma[i].Init.PeriphInc = DMA_PINC_DISABLE;
    dma[i].Init.MemInc = DMA_MINC_ENABLE;
    dma[i].Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    dma[i].Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
    dma[i].Init.Mode = DMA_NORMAL;
    dma[i].Init.Priority = DMA_PRIORITY_HIGH;
    if (HAL_DMA_Init(&dma[i]) != HAL_OK) return HAL_ERROR;
    adc->DMA_Handle = &dma[i];
    dma[i].Parent = adc;
    return HAL_OK;
}

int AdcDmaDiag_Start(uint32_t now)
{
    if (attempted || !is_locked || !is_locked() || AdcDmaDiag_Busy() ||
        !FocAdcClock_IsExpected() || (ADC12_COMMON->CCR & ADC_CCR_DUAL) ||
        (TIM1->CR1 & TIM_CR1_CEN) || TIM1->PSC != 0U || TIM1->ARR != 4249U ||
        TIM1->CCR4 != 3500U ||
        (TIM1->CR2 & TIM_CR2_MMS2) != TIM_TRGO2_OC4REF)
        return 0;
    attempted = 1U; /* Even a failed setup cannot be silently retried. */
    result.state = ADC_DMA_DIAG_ARMING;
    result.reason = ADC_DMA_DIAG_OK;
    done_mask = configured = 0U;
    started_ms = now;
    StopTrigger();
    for (unsigned i = 0; i < 2U; ++i) {
        saved_init[i] = adcs[i]->Init;
        saved_dma[i] = adcs[i]->DMA_Handle;
        saved_sqr[i][0] = adcs[i]->Instance->SQR1;
        saved_sqr[i][1] = adcs[i]->Instance->SQR2;
        saved_sqr[i][2] = adcs[i]->Instance->SQR3;
        saved_sqr[i][3] = adcs[i]->Instance->SQR4;
        saved_smpr[i][0] = adcs[i]->Instance->SMPR1;
        saved_smpr[i][1] = adcs[i]->Instance->SMPR2;
    }
    if (HAL_ADCEx_InjectedStop_IT(adcs[0]) != HAL_OK ||
        HAL_ADCEx_InjectedStop(adcs[1]) != HAL_OK) {
        Fail(ADC_DMA_DIAG_CONFIG);
        return 0;
    }
    __HAL_RCC_DMA1_CLK_ENABLE();
    __HAL_RCC_DMAMUX1_CLK_ENABLE();
    if (Configure(0U) != HAL_OK || Configure(1U) != HAL_OK) {
        Fail(ADC_DMA_DIAG_CONFIG);
        return 0;
    }
    configured = 1U;
    HAL_NVIC_SetPriority(DMA1_Channel3_IRQn, 0U, 0U);
    HAL_NVIC_SetPriority(DMA1_Channel4_IRQn, 0U, 0U);
    HAL_NVIC_ClearPendingIRQ(DMA1_Channel3_IRQn);
    HAL_NVIC_ClearPendingIRQ(DMA1_Channel4_IRQn);
    HAL_NVIC_EnableIRQ(DMA1_Channel3_IRQn);
    HAL_NVIC_EnableIRQ(DMA1_Channel4_IRQn);
    if (HAL_ADC_Start_DMA(adcs[1], (uint32_t *)raw_v, ADC_DMA_DIAG_PAIRS) != HAL_OK ||
        HAL_ADC_Start_DMA(adcs[0], (uint32_t *)raw_u,
                          ADC_DMA_DIAG_PAIRS * ADC_DMA_DIAG_U_STRIDE) != HAL_OK) {
        Fail(ADC_DMA_DIAG_CONFIG);
        return 0;
    }
    __HAL_DMA_DISABLE_IT(&dma[0], DMA_IT_HT);
    __HAL_DMA_DISABLE_IT(&dma[1], DMA_IT_HT);
    if (!is_locked() || !(ADC1->CR & ADC_CR_ADSTART) || !(ADC2->CR & ADC_CR_ADSTART) ||
        !(DMA1_Channel3->CCR & DMA_CCR_EN) || !(DMA1_Channel4->CCR & DMA_CCR_EN) ||
        DMA1_Channel3->CNDTR != ADC_DMA_DIAG_PAIRS * ADC_DMA_DIAG_U_STRIDE ||
        DMA1_Channel4->CNDTR != ADC_DMA_DIAG_PAIRS) {
        Fail(ADC_DMA_DIAG_CONFIG);
        return 0;
    }
    /* Both independently triggered ADCs and DMA writers are armed BEFORE CEN. */
    TIM1->CR1 &= ~TIM_CR1_DIR;
    TIM1->CNT = 0U;
    __DMB();
    result.state = ADC_DMA_DIAG_RUNNING;
    TIM1->CR1 |= TIM_CR1_CEN; /* OC4REF internal trigger only: no PWM pin enable. */
    return 1;
}

void AdcDmaDiag_Complete(ADC_HandleTypeDef *adc)
{
    if (result.state != ADC_DMA_DIAG_RUNNING) return;
    unsigned i = adc == adcs[0] ? 0U : 1U;
    if (adc != adcs[i] || !is_locked()) { Fail(ADC_DMA_DIAG_UNSAFE); return; }
    if (i == 0U) ++result.irq_u; else ++result.irq_v;
    if (__HAL_DMA_GET_COUNTER(&dma[i]) != 0U) { Fail(ADC_DMA_DIAG_COUNT_ERROR); return; }
    done_mask |= (uint8_t)(1U << i);
    if (done_mask == 3U) {
        StopTrigger();
        result.state = ADC_DMA_DIAG_STOPPING;
    }
}

void AdcDmaDiag_Error(ADC_HandleTypeDef *adc)
{
    if (!AdcDmaDiag_Busy()) return;
    if (adc == adcs[0]) result.adc_error_u |= HAL_ADC_GetError(adc);
    if (adc == adcs[1]) result.adc_error_v |= HAL_ADC_GetError(adc);
    Fail(ADC_DMA_DIAG_ADC_ERROR);
}

void AdcDmaDiag_Service(uint32_t now)
{
    if (result.state == ADC_DMA_DIAG_RUNNING) {
        if (!is_locked()) Fail(ADC_DMA_DIAG_UNSAFE);
        else if ((uint32_t)(now - started_ms) >= ADC_DMA_DIAG_TIMEOUT_MS)
            Fail(ADC_DMA_DIAG_TIMEOUT);
    }
    if (result.state != ADC_DMA_DIAG_STOPPING) return;
    StopTrigger();
    result.elapsed_ms = now - started_ms;
    uint32_t successful = configured && done_mask == 3U && !result.reason;
    uint32_t u_values = configured ? ADC_DMA_DIAG_PAIRS * ADC_DMA_DIAG_U_STRIDE -
                                    __HAL_DMA_GET_COUNTER(&dma[0]) : 0U;
    result.count_u = u_values / ADC_DMA_DIAG_U_STRIDE;
    result.count_v = configured ? ADC_DMA_DIAG_PAIRS - __HAL_DMA_GET_COUNTER(&dma[1]) : 0U;
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    result.count_u = (u_values + 1U) / 2U;
    result.count_w = u_values / 2U;
    if (u_values % 2U) successful = 0U;
#endif
    for (unsigned i = 0U; i < 2U; ++i) {
        uint32_t errors = HAL_ADC_GetError(adcs[i]);
        if (adcs[i]->Instance->ISR & ADC_FLAG_OVR) errors |= HAL_ADC_ERROR_OVR;
        if (i == 0U) result.adc_error_u |= errors; else result.adc_error_v |= errors;
        if (errors) successful = 0U;
    }
    if (result.adc_error_u || result.adc_error_v) result.reason = ADC_DMA_DIAG_ADC_ERROR;
    /* Foreground cleanup only: never blocking HAL calls from the ADC/DMA IRQ. */
    uint32_t restored = 1U;
    HAL_NVIC_DisableIRQ(DMA1_Channel3_IRQn);
    HAL_NVIC_DisableIRQ(DMA1_Channel4_IRQn);
    for (unsigned i = 0; i < 2U; ++i) {
        if (adcs[i]->DMA_Handle == &dma[i]) {
            restored &= HAL_ADC_Stop_DMA(adcs[i]) == HAL_OK;
            if (dma[i].Instance) {
                __HAL_DMA_DISABLE_IT(&dma[i], DMA_IT_HT | DMA_IT_TC | DMA_IT_TE);
                __HAL_DMA_DISABLE(&dma[i]);
            }
        } else {
            restored &= HAL_ADCEx_InjectedStop(adcs[i]) == HAL_OK;
            restored &= HAL_ADC_Stop(adcs[i]) == HAL_OK;
        }
        adcs[i]->Init = saved_init[i];
        adcs[i]->DMA_Handle = saved_dma[i];
        restored &= HAL_ADC_Init(adcs[i]) == HAL_OK;
        if (adcs[i]->Instance->CR & (ADC_CR_ADSTART | ADC_CR_JADSTART)) restored = 0U;
        if (restored) {
            adcs[i]->Instance->SQR1 = saved_sqr[i][0];
            adcs[i]->Instance->SQR2 = saved_sqr[i][1];
            adcs[i]->Instance->SQR3 = saved_sqr[i][2];
            adcs[i]->Instance->SQR4 = saved_sqr[i][3];
            adcs[i]->Instance->SMPR1 = saved_smpr[i][0];
            adcs[i]->Instance->SMPR2 = saved_smpr[i][1];
        }
    }
    HAL_NVIC_ClearPendingIRQ(DMA1_Channel3_IRQn);
    HAL_NVIC_ClearPendingIRQ(DMA1_Channel4_IRQn);
    if (restored) restored = HAL_ADCEx_InjectedStart(adcs[1]) == HAL_OK &&
                             HAL_ADCEx_InjectedStart_IT(adcs[0]) == HAL_OK;
    result.restored = restored;
    if (!restored) { result.reason = ADC_DMA_DIAG_STOP_ERROR; successful = 0U; }
    if (!is_locked()) { result.reason = ADC_DMA_DIAG_UNSAFE; successful = 0U; }
    if (successful && result.count_u == ADC_DMA_DIAG_PAIRS &&
        result.count_v == ADC_DMA_DIAG_PAIRS && result.irq_u == 1U && result.irq_v == 1U) {
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        AdcRawThreePhaseReport report;
        int summarized = AdcRaw_SummarizeThreePhase(raw_u, raw_v, ADC_DMA_DIAG_PAIRS, &report);
#else
        AdcRawReport report;
        int summarized = AdcRaw_Summarize(raw_u, raw_v, ADC_DMA_DIAG_PAIRS, &report);
#endif
        if (!summarized) {
            result.reason = ADC_DMA_DIAG_COUNT_ERROR;
            successful = 0U;
        } else {
            result.min_u = report.min_u; result.max_u = report.max_u;
            result.min_v = report.min_v; result.max_v = report.max_v;
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
            result.min_w = report.min_w; result.max_w = report.max_w;
#endif
            result.crc32 = report.crc32;
        }
    } else {
        if (!result.reason) result.reason = ADC_DMA_DIAG_COUNT_ERROR;
        successful = 0U;
    }
    __DMB();
    result.state = successful ? ADC_DMA_DIAG_READY : ADC_DMA_DIAG_FAILED;
}

void AdcDmaDiag_Snapshot(AdcDmaDiagStatus *status)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    *status = result;
    __set_PRIMASK(mask);
}

int AdcDmaDiag_Read(uint32_t index, uint16_t *u, uint16_t *v)
{
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    /* Never silently export a UV pair to a legacy two-channel consumer. */
    (void)index; (void)u; (void)v;
    return 0;
#else
    if (!u || !v || result.state != ADC_DMA_DIAG_READY || index >= ADC_DMA_DIAG_PAIRS) return 0;
    __DMB();
    *u = raw_u[index]; *v = raw_v[index];
    return 1;
#endif
}

#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
int AdcDmaDiag_ReadThreePhase(uint32_t index, uint16_t *u, uint16_t *v, uint16_t *w)
{
    if (!u || !v || !w || result.state != ADC_DMA_DIAG_READY || index >= ADC_DMA_DIAG_PAIRS)
        return 0;
    __DMB();
    *u = raw_u[2U * index]; *v = raw_v[index]; *w = raw_u[2U * index + 1U];
    return 1;
}
#endif

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *adc) { AdcDmaDiag_Complete(adc); }
void DMA1_Channel3_IRQHandler(void) { HAL_DMA_IRQHandler(&dma[0]); }
void DMA1_Channel4_IRQHandler(void) { HAL_DMA_IRQHandler(&dma[1]); }
