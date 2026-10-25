#include "adc_dma_diag.h"
#include "foc_adc_clock_stm32.h"
#include "adc_raw_report.h"
#include <string.h>

#if !defined(ZERO_RETEST_BOOT) || !defined(ADC_DMA_RAW_DIAGNOSTIC) || \
    !defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC) || !defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
#error "Parallel raw capture requires the standalone hard-off profile"
#endif

#if defined(ADC_DMA_PA1_ONLY_DIAGNOSTIC) && defined(ADC_DMA_ADC12_ONLY_DIAGNOSTIC)
#error "Select only one locked ADC contrast profile"
#endif

#if defined(ADC_DMA_PA1_ONLY_DIAGNOSTIC) || defined(ADC_DMA_ADC12_ONLY_DIAGNOSTIC)
#if !defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
#error "ADC contrast requires the locked 247.5-cycle profile"
#endif
#endif
#if defined(ADC_DMA_PA1_ONLY_DIAGNOSTIC)
#define CAPTURE_MASK 2U
#elif defined(ADC_DMA_ADC12_ONLY_DIAGNOSTIC)
#define CAPTURE_MASK 3U
#else
#define CAPTURE_MASK 7U
#endif

/* Independent ADC1/2/5, not a three-ADC hardware multimode. One common TIM1
 * event removes the U->W rank delay; cross-group aperture skew is not measured. */
static ADC_HandleTypeDef w_adc;
static ADC_HandleTypeDef *adcs[3];
static DMA_HandleTypeDef dma[3];
static const IRQn_Type irqs[3] = {DMA1_Channel3_IRQn, DMA1_Channel4_IRQn, DMA2_Channel1_IRQn};
static ADC_InitTypeDef saved_init[2];
static DMA_HandleTypeDef *saved_dma[2];
static uint32_t saved_sqr[2][4], saved_smpr[2][2];
#if defined(ADC_DMA_REFERENCE_DOUBLE_CAPTURE)
/* W is never acquired in this profile. Only the two DMA destinations consume
 * SRAM; export pads W explicitly. Default 4096/triple profiles are unchanged. */
static uint16_t raw[2][ADC_DMA_DIAG_PAIRS] __attribute__((aligned(4)));
#else
static uint16_t raw[3][ADC_DMA_DIAG_PAIRS] __attribute__((aligned(4)));
#endif
static volatile AdcDmaDiagStatus result;
static uint8_t (*is_locked)(void);
static uint32_t started_ms;
static volatile uint8_t done_mask;
static uint8_t attempted, configured_mask, prepared;

static int InactiveAdcsStopped(void)
{
    for (unsigned i = 0U; i < 3U; ++i) {
        if (!(CAPTURE_MASK & (1U << i)) &&
            (adcs[i]->Instance->CR & (ADC_CR_ADSTART | ADC_CR_JADSTART))) return 0;
    }
    return 1;
}

static void StopTrigger(void)
{
    TIM1->CR1 &= ~TIM_CR1_CEN;
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    __DSB();
}

int AdcDmaDiag_ParallelReady(void)
{
    return prepared && FocAdcClock_IsExpected() &&
        __HAL_RCC_GET_ADC345_SOURCE() == RCC_ADC345CLKSOURCE_SYSCLK &&
        (ADC345_COMMON->CCR & (ADC_CCR_CKMODE | ADC_CCR_PRESC | ADC_CCR_DUAL)) ==
            FOC_ADC_CLOCK_PRESCALER;
}

void AdcDmaDiag_Init(ADC_HandleTypeDef *u, ADC_HandleTypeDef *v, uint8_t (*locked)(void))
{
    adcs[0] = u; adcs[1] = v; adcs[2] = &w_adc; is_locked = locked;
    if (!u || !v || !locked || !locked() || (TIM1->CR1 & TIM_CR1_CEN)) return;
    RCC_PeriphCLKInitTypeDef clock = {0};
    clock.PeriphClockSelection = RCC_PERIPHCLK_ADC345;
    clock.Adc345ClockSelection = RCC_ADC345CLKSOURCE_SYSCLK;
    if (HAL_RCCEx_PeriphCLKConfig(&clock) != HAL_OK) return;
    __HAL_RCC_ADC345_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    GPIO_InitTypeDef gpio = {0};
    gpio.Pin = GPIO_PIN_8; gpio.Mode = GPIO_MODE_ANALOG; gpio.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &gpio);
    w_adc.Instance = ADC5;
    w_adc.Init = u->Init;
    w_adc.Init.ScanConvMode = ADC_SCAN_DISABLE;
    w_adc.Init.NbrOfConversion = 1U;
    w_adc.Init.ClockPrescaler = FOC_ADC_CLOCK_PRESCALER;
    if (HAL_ADC_Init(&w_adc) != HAL_OK ||
        HAL_ADCEx_Calibration_Start(&w_adc, ADC_SINGLE_ENDED) != HAL_OK) return;
    prepared = 1U;
}

int AdcDmaDiag_Busy(void)
{
    return result.state == ADC_DMA_DIAG_ARMING || result.state == ADC_DMA_DIAG_RUNNING ||
           result.state == ADC_DMA_DIAG_STOPPING;
}

static void Fail(uint32_t reason)
{
    StopTrigger();
    if (!result.reason) result.reason = reason;
    result.state = ADC_DMA_DIAG_STOPPING;
}

static HAL_StatusTypeDef Configure(unsigned i)
{
    ADC_HandleTypeDef *adc = adcs[i];
    adc->Init.ScanConvMode = ADC_SCAN_DISABLE;
    adc->Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    adc->Init.LowPowerAutoWait = DISABLE;
    adc->Init.ContinuousConvMode = DISABLE;
    adc->Init.NbrOfConversion = 1U;
    adc->Init.DiscontinuousConvMode = DISABLE;
    adc->Init.ExternalTrigConv = ADC_EXTERNALTRIG_T1_TRGO2;
    adc->Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
    adc->Init.DMAContinuousRequests = ENABLE;
    adc->Init.Overrun = ADC_OVR_DATA_PRESERVED;
    adc->Init.OversamplingMode = DISABLE;
    if (HAL_ADC_Init(adc) != HAL_OK) return HAL_ERROR;
    ADC_ChannelConfTypeDef channel = {0};
    channel.Channel = i == 1U ? ADC_CHANNEL_2 : ADC_CHANNEL_1;
    channel.Rank = ADC_REGULAR_RANK_1;
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
    channel.SamplingTime = ADC_SAMPLETIME_247CYCLES_5;
#else
    channel.SamplingTime = ADC_SAMPLETIME_12CYCLES_5;
#endif
    channel.SingleDiff = ADC_SINGLE_ENDED;
    channel.OffsetNumber = ADC_OFFSET_NONE;
    if (HAL_ADC_ConfigChannel(adc, &channel) != HAL_OK) return HAL_ERROR;
    dma[i].Instance = i == 0U ? DMA1_Channel3 : (i == 1U ? DMA1_Channel4 : DMA2_Channel1);
    dma[i].Init.Request = i == 0U ? DMA_REQUEST_ADC1 : (i == 1U ? DMA_REQUEST_ADC2 : DMA_REQUEST_ADC5);
    dma[i].Init.Direction = DMA_PERIPH_TO_MEMORY;
    dma[i].Init.PeriphInc = DMA_PINC_DISABLE;
    dma[i].Init.MemInc = DMA_MINC_ENABLE;
    dma[i].Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    dma[i].Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
    dma[i].Init.Mode = DMA_NORMAL;
    dma[i].Init.Priority = DMA_PRIORITY_HIGH;
    if (HAL_DMA_Init(&dma[i]) != HAL_OK) return HAL_ERROR;
    adc->DMA_Handle = &dma[i]; dma[i].Parent = adc;
    configured_mask |= (uint8_t)(1U << i);
    return HAL_OK;
}

int AdcDmaDiag_Start(uint32_t now)
{
    if (attempted || !is_locked || !is_locked() || AdcDmaDiag_Busy() ||
        !AdcDmaDiag_ParallelReady() || (ADC12_COMMON->CCR & ADC_CCR_DUAL) ||
        (TIM1->CR1 & TIM_CR1_CEN) || TIM1->PSC != 0U || TIM1->ARR != 4249U ||
        TIM1->CCR4 != 3500U || (TIM1->CR2 & TIM_CR2_MMS2) != TIM_TRGO2_OC4REF) return 0;
    attempted = 1U;
    result.state = ADC_DMA_DIAG_ARMING; started_ms = now;
    StopTrigger();
    for (unsigned i = 0U; i < 2U; ++i) {
        saved_init[i] = adcs[i]->Init; saved_dma[i] = adcs[i]->DMA_Handle;
        saved_sqr[i][0] = adcs[i]->Instance->SQR1; saved_sqr[i][1] = adcs[i]->Instance->SQR2;
        saved_sqr[i][2] = adcs[i]->Instance->SQR3; saved_sqr[i][3] = adcs[i]->Instance->SQR4;
        saved_smpr[i][0] = adcs[i]->Instance->SMPR1; saved_smpr[i][1] = adcs[i]->Instance->SMPR2;
    }
    if (HAL_ADCEx_InjectedStop_IT(adcs[0]) != HAL_OK ||
        HAL_ADCEx_InjectedStop(adcs[1]) != HAL_OK) { Fail(ADC_DMA_DIAG_CONFIG); return 0; }
    __HAL_RCC_DMA1_CLK_ENABLE(); __HAL_RCC_DMA2_CLK_ENABLE(); __HAL_RCC_DMAMUX1_CLK_ENABLE();
    for (unsigned i = 0U; i < 3U; ++i) {
        if (!(CAPTURE_MASK & (1U << i))) continue;
        if (Configure(i) != HAL_OK) { Fail(ADC_DMA_DIAG_CONFIG); return 0; }
        HAL_NVIC_SetPriority(irqs[i], 0U, 0U);
        HAL_NVIC_ClearPendingIRQ(irqs[i]); HAL_NVIC_EnableIRQ(irqs[i]);
    }
    HAL_NVIC_SetPriority(ADC5_IRQn, 0U, 0U);
    HAL_NVIC_ClearPendingIRQ(ADC5_IRQn); HAL_NVIC_EnableIRQ(ADC5_IRQn);
    for (unsigned i = 0U; i < 3U; ++i) {
        if (!(CAPTURE_MASK & (1U << i))) continue;
        if (HAL_ADC_Start_DMA(adcs[i], (uint32_t *)raw[i], ADC_DMA_DIAG_PAIRS) != HAL_OK) {
            Fail(ADC_DMA_DIAG_CONFIG); return 0;
        }
        __HAL_DMA_DISABLE_IT(&dma[i], DMA_IT_HT);
    }
    for (unsigned i = 0U; i < 3U; ++i) {
        if (!(CAPTURE_MASK & (1U << i))) continue;
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
        /* Verify actual SMPR before enabling any internal trigger. These are
         * single-rank channel 1 (U/W) or channel 2 (V), not background inputs. */
        uint32_t channel = i == 1U ? ADC_CHANNEL_2 : ADC_CHANNEL_1;
        if (LL_ADC_GetChannelSamplingTime(adcs[i]->Instance, channel) !=
                ADC_SAMPLETIME_247CYCLES_5) {
            Fail(ADC_DMA_DIAG_CONFIG); return 0;
        }
        result.sampling_checked_mask |= 1U << i;
#endif
        if (!(adcs[i]->Instance->CR & ADC_CR_ADSTART) ||
            !(dma[i].Instance->CCR & DMA_CCR_EN) ||
            __HAL_DMA_GET_COUNTER(&dma[i]) != ADC_DMA_DIAG_PAIRS) {
            Fail(ADC_DMA_DIAG_CONFIG); return 0;
        }
    }
    if (!is_locked() || !AdcDmaDiag_ParallelReady() || !InactiveAdcsStopped()) {
        Fail(ADC_DMA_DIAG_UNSAFE); return 0;
    }
    TIM1->CR1 &= ~TIM_CR1_DIR; TIM1->CNT = 0U;
    __DMB(); result.state = ADC_DMA_DIAG_RUNNING;
    TIM1->CR1 |= TIM_CR1_CEN; /* Internal trigger only; output bits remain hard off. */
    return 1;
}

void AdcDmaDiag_Complete(ADC_HandleTypeDef *adc)
{
    if (result.state != ADC_DMA_DIAG_RUNNING) return;
    unsigned i;
    for (i = 0U; i < 3U && adc != adcs[i]; ++i) {}
    if (i == 3U || !(CAPTURE_MASK & (1U << i)) || !is_locked() || !InactiveAdcsStopped()) {
        Fail(ADC_DMA_DIAG_UNSAFE); return;
    }
    if (i == 0U) ++result.irq_u; else if (i == 1U) ++result.irq_v; else ++result.irq_w;
    if ((done_mask & (1U << i)) || __HAL_DMA_GET_COUNTER(&dma[i])) {
        Fail(ADC_DMA_DIAG_COUNT_ERROR); return;
    }
    done_mask |= (uint8_t)(1U << i);
    if (done_mask == CAPTURE_MASK) { StopTrigger(); result.state = ADC_DMA_DIAG_STOPPING; }
}

void AdcDmaDiag_Error(ADC_HandleTypeDef *adc)
{
    if (!AdcDmaDiag_Busy()) return;
    if (adc == adcs[0]) result.adc_error_u |= HAL_ADC_GetError(adc);
    if (adc == adcs[1]) result.adc_error_v |= HAL_ADC_GetError(adc);
    if (adc == adcs[2]) result.adc_error_w |= HAL_ADC_GetError(adc);
    Fail(ADC_DMA_DIAG_ADC_ERROR);
}

void AdcDmaDiag_Service(uint32_t now)
{
    if (result.state == ADC_DMA_DIAG_RUNNING) {
        if (!is_locked() || !InactiveAdcsStopped()) Fail(ADC_DMA_DIAG_UNSAFE);
        else if ((uint32_t)(now - started_ms) >= ADC_DMA_DIAG_TIMEOUT_MS) Fail(ADC_DMA_DIAG_TIMEOUT);
    }
    if (result.state != ADC_DMA_DIAG_STOPPING) return;
    StopTrigger(); result.elapsed_ms = now - started_ms;
    uint32_t successful = configured_mask == CAPTURE_MASK && done_mask == CAPTURE_MASK && !result.reason;
    uint32_t counts[3], errors[3], restored = 1U;
    for (unsigned i = 0U; i < 3U; ++i) {
        uint32_t remaining = (configured_mask & (1U << i)) ? __HAL_DMA_GET_COUNTER(&dma[i]) : ADC_DMA_DIAG_PAIRS;
        counts[i] = remaining <= ADC_DMA_DIAG_PAIRS ? ADC_DMA_DIAG_PAIRS - remaining : 0U;
        errors[i] = (CAPTURE_MASK & (1U << i)) ? HAL_ADC_GetError(adcs[i]) : 0U;
        if ((CAPTURE_MASK & (1U << i)) && (adcs[i]->Instance->ISR & ADC_FLAG_OVR)) errors[i] |= HAL_ADC_ERROR_OVR;
        if (errors[i]) successful = 0U;
        HAL_NVIC_DisableIRQ(irqs[i]);
    }
    result.count_u = counts[0]; result.count_v = counts[1]; result.count_w = counts[2];
    result.adc_error_u |= errors[0]; result.adc_error_v |= errors[1]; result.adc_error_w |= errors[2];
    if (result.adc_error_u || result.adc_error_v || result.adc_error_w) result.reason = ADC_DMA_DIAG_ADC_ERROR;
    HAL_NVIC_DisableIRQ(ADC5_IRQn);
    for (unsigned i = 0U; i < 3U; ++i) {
        if (adcs[i]->DMA_Handle == &dma[i]) {
            restored &= HAL_ADC_Stop_DMA(adcs[i]) == HAL_OK;
            __HAL_DMA_DISABLE_IT(&dma[i], DMA_IT_HT | DMA_IT_TC | DMA_IT_TE);
            __HAL_DMA_DISABLE(&dma[i]);
        } else {
            restored &= HAL_ADCEx_InjectedStop(adcs[i]) == HAL_OK;
            restored &= HAL_ADC_Stop(adcs[i]) == HAL_OK;
        }
        if (adcs[i]->Instance->CR & (ADC_CR_ADSTART | ADC_CR_JADSTART)) restored = 0U;
        if (i < 2U) {
            adcs[i]->Init = saved_init[i]; adcs[i]->DMA_Handle = saved_dma[i];
            restored &= HAL_ADC_Init(adcs[i]) == HAL_OK;
            if (!(adcs[i]->Instance->CR & (ADC_CR_ADSTART | ADC_CR_JADSTART))) {
                adcs[i]->Instance->SQR1 = saved_sqr[i][0]; adcs[i]->Instance->SQR2 = saved_sqr[i][1];
                adcs[i]->Instance->SQR3 = saved_sqr[i][2]; adcs[i]->Instance->SQR4 = saved_sqr[i][3];
                adcs[i]->Instance->SMPR1 = saved_smpr[i][0]; adcs[i]->Instance->SMPR2 = saved_smpr[i][1];
            } else restored = 0U;
        }
        HAL_NVIC_ClearPendingIRQ(irqs[i]);
    }
    HAL_NVIC_ClearPendingIRQ(ADC5_IRQn);
    if (restored) restored = HAL_ADCEx_InjectedStart(adcs[1]) == HAL_OK &&
                             HAL_ADCEx_InjectedStart_IT(adcs[0]) == HAL_OK;
    result.restored = restored;
    if (!restored) { result.reason = ADC_DMA_DIAG_STOP_ERROR; successful = 0U; }
    if (!is_locked() || !AdcDmaDiag_ParallelReady()) { result.reason = ADC_DMA_DIAG_UNSAFE; successful = 0U; }
    const uint32_t irq_counts[3] = {result.irq_u, result.irq_v, result.irq_w};
    for (unsigned i = 0U; i < 3U; ++i) {
        const uint32_t active = (CAPTURE_MASK >> i) & 1U;
        if (counts[i] != active * ADC_DMA_DIAG_PAIRS || irq_counts[i] != active) successful = 0U;
    }
    if (successful) {
        AdcRawThreePhaseReport report;
#if defined(ADC_DMA_REFERENCE_DOUBLE_CAPTURE)
        if (AdcRaw_SummarizeUvPadding(raw[0], raw[1], ADC_DMA_DIAG_PAIRS, &report)) {
#else
        if (AdcRaw_SummarizeParallel(raw[0], raw[1], raw[2], ADC_DMA_DIAG_PAIRS, &report)) {
#endif
            result.min_u = report.min_u; result.max_u = report.max_u;
            result.min_v = report.min_v; result.max_v = report.max_v;
            result.min_w = report.min_w; result.max_w = report.max_w; result.crc32 = report.crc32;
        } else { result.reason = ADC_DMA_DIAG_COUNT_ERROR; successful = 0U; }
    } else {
        if (!result.reason) result.reason = ADC_DMA_DIAG_COUNT_ERROR;
        successful = 0U;
    }
    __DMB(); result.state = successful ? ADC_DMA_DIAG_READY : ADC_DMA_DIAG_FAILED;
}

void AdcDmaDiag_Snapshot(AdcDmaDiagStatus *status)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq(); *status = result; __set_PRIMASK(mask);
}

int AdcDmaDiag_Read(uint32_t index, uint16_t *u, uint16_t *v)
{ (void)index; (void)u; (void)v; return 0; }

int AdcDmaDiag_ReadThreePhase(uint32_t index, uint16_t *u, uint16_t *v, uint16_t *w)
{
    if (!u || !v || !w || result.state != ADC_DMA_DIAG_READY || index >= ADC_DMA_DIAG_PAIRS) return 0;
    __DMB(); *u = raw[0][index]; *v = raw[1][index];
#if defined(ADC_DMA_REFERENCE_DOUBLE_CAPTURE)
    *w = 0U; /* Explicitly unsampled padding; no third-array access. */
#else
    *w = raw[2][index];
#endif
    return 1;
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *adc) { AdcDmaDiag_Complete(adc); }
void DMA1_Channel3_IRQHandler(void) { HAL_DMA_IRQHandler(&dma[0]); }
void DMA1_Channel4_IRQHandler(void) { HAL_DMA_IRQHandler(&dma[1]); }
void DMA2_Channel1_IRQHandler(void) { HAL_DMA_IRQHandler(&dma[2]); }
void ADC5_IRQHandler(void) { HAL_ADC_IRQHandler(&w_adc); }
