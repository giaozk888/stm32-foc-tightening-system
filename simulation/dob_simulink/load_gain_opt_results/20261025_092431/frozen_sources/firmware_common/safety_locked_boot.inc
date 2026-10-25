/* Included by A/B main.c after the HAL sampling helpers. Not a safety certification.
 * No motor/Protocol/BootHealth/Router tasks, PWM start, Flash writes or unlock path.
 * It intentionally cannot auto-confirm an IAP trial; deployment policy is pending.
 */
#include "safety_guard.h"

static void SafetyLocked_ForceOff(void)
{
    PowerStage_Disable();
    foc_enable = 0U;
    analog_safe_latched = 1U;
    PWM_StopAll();
    __HAL_TIM_MOE_DISABLE(&htim1);
}

static HAL_StatusTypeDef SafetyLocked_ReadOne(uint32_t channel, uint16_t *raw)
{
    ADC_ChannelConfTypeDef cfg = {0};
    HAL_StatusTypeDef result;
    /* No injected sampling exists in this profile. Unlike the running-FOC
     * helper, regular conversion can safely be stopped after a timeout. */
    if (HAL_ADC_Stop(&hadc2) != HAL_OK) return HAL_ERROR;
    cfg.Channel = channel;
    cfg.Rank = ADC_REGULAR_RANK_1;
    cfg.SamplingTime = ADC_SAMPLETIME_247CYCLES_5;
    cfg.SingleDiff = ADC_SINGLE_ENDED;
    cfg.OffsetNumber = ADC_OFFSET_NONE;
    if (HAL_ADC_ConfigChannel(&hadc2, &cfg) != HAL_OK) return HAL_ERROR;
    result = HAL_ADC_Start(&hadc2);
    if (result == HAL_OK) result = HAL_ADC_PollForConversion(&hadc2, 2U);
    if (result == HAL_OK) *raw = (uint16_t)HAL_ADC_GetValue(&hadc2);
    if (HAL_ADC_Stop(&hadc2) != HAL_OK) result = HAL_ERROR;
    return result;
}

static void SafetyLocked_Read(SafetySample *sample, uint32_t channel,
                              uint8_t adc_ready, const SafetySamplePolicy *policy)
{
    uint16_t raw[3] = {0U, 0U, 0U};
    uint8_t ok = adc_ready;
    for (unsigned int i = 0U; i < 3U && ok; ++i)
        ok = SafetyLocked_ReadOne(channel, &raw[i]) == HAL_OK;
    SafetySample_Update(sample, raw, ok, HAL_GetTick(), policy);
}

static void __attribute__((noreturn)) SafetyLockedBoot_RunForever(void)
{
    SafetySample pc4, pc5;
    /* 60 counts is an existing diagnostic threshold, NOT a calibrated safety tolerance. */
    const SafetySamplePolicy policy = {0U, 4095U, 60U, 0U};
    SafetyEvidence evidence = {0};
    GPIO_InitTypeDef gpio = {0};
    ADC_MultiModeTypeDef mode = {0};
    uint16_t sequence = 0U;
    uint32_t last_print = 0U;
    uint8_t data[8];
    uint8_t adc_ready;
    SafetyLocked_ForceOff();
    SafetySample_Reset(&pc4);
    SafetySample_Reset(&pc5);
    evidence.boot_locked = 1U;
    UART_SendString("SAFETY LOCKED BOOT: SD=0 MOE=0 FOC=0; no motor/command tasks, no auto-confirm\r\n");
    (void)CAN_StatusTx_Init();
    gpio.Pin = GPIO_PIN_4 | GPIO_PIN_5;
    gpio.Mode = GPIO_MODE_ANALOG;
    gpio.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOC, &gpio);
    /* Only regular ADC2 diagnostics. No injected ADC, current zero or bridge calibration. */
    mode.Mode = ADC_MODE_INDEPENDENT;
    mode.DMAAccessMode = ADC_DMAACCESSMODE_DISABLED;
    mode.TwoSamplingDelay = ADC_TWOSAMPLINGDELAY_1CYCLE;
    adc_ready = HAL_ADCEx_MultiModeConfigChannel(&hadc1, &mode) == HAL_OK;
    if (adc_ready)
        adc_ready = HAL_ADCEx_Calibration_Start(&hadc2, ADC_SINGLE_ENDED) == HAL_OK;
    for (;;)
    {
        CAN_StatusTx_Health health;
        BootMetaV2_t meta;
        uint8_t pc4_reasons, pc5_reasons;
        uint16_t missing;
        uint32_t now;
        SafetyLocked_ForceOff();
        SafetyLocked_Read(&pc4, ADC_CHANNEL_5, adc_ready, &policy);
        SafetyLocked_Read(&pc5, ADC_CHANNEL_11, adc_ready, &policy);
        now = HAL_GetTick();
        CAN_StatusTx_Service(now);
        CAN_StatusTx_GetHealth(&health);
        /* Controller ready != end-to-end link verified. All unimplemented adapters stay false. */
        evidence.feedback_ms = now;
        evidence.firmware_confirmed = (BootMeta_ReadV3(&meta) != 0U) &&
            meta.confirmed_slot == APP_THIS_SLOT && meta.pending_slot == BOOT_SLOT_NONE;
        /* Sticky fault in this profile: recovery or clean readings never re-arm. */
        evidence.fault_latched |= !adc_ready || !pc4.acquisition_ok ||
            !pc5.acquisition_ok || health.recovery_exhausted ||
            HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) != GPIO_PIN_RESET ||
            (htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U;
        pc4_reasons = SafetySample_Reasons(&pc4, &policy, now);
        pc5_reasons = SafetySample_Reasons(&pc5, &policy, now);
        evidence.fault_latched |= ((pc4_reasons | pc5_reasons) &
            (SAMPLE_ACQUISITION | SAMPLE_RANGE | SAMPLE_DISAGREE | SAMPLE_STALE)) != 0U;
        missing = SafetyGuard_Missing(&evidence, pc4_reasons, pc5_reasons, now);
        CAN_StatusTx_Publish(MOTOR_MODE_IDLE,
            evidence.fault_latched ? CAN_STATUS_FLAG_FAULT_LATCHED : 0U,
            evidence.fault_latched ? 8U : 0U); /* 8: locked diagnostic acquisition/output fault */
        CAN_StatusTx_PublishMotor(0.0f, 0.0f, 0U, 0U);
        CAN_StatusTx_PublishElectrical(0U, 0.0f, 0U, 0U);
        vTaskDelay(pdMS_TO_TICKS(5U));
        SafetyGuard_EncodeLocked(missing, adc_ready, pc4_reasons, pc5_reasons, sequence, data);
        (void)CAN_StatusTx_TrySafetyFrame(SAFETY_REPORT_ID, data);
        SafetyGuard_EncodeRaw(&pc4, sequence, data);
        (void)CAN_StatusTx_TrySafetyFrame(SAFETY_PC4_RAW_ID, data);
        SafetyGuard_EncodeRaw(&pc5, sequence, data);
        (void)CAN_StatusTx_TrySafetyFrame(SAFETY_PC5_RAW_ID, data);
        ++sequence; /* Diagnostic attempts, not proof of delivery. */
        if ((uint32_t)(now - last_print) >= 1000U) {
            char msg[240];
            last_print = now;
            snprintf(msg, sizeof(msg),
                "SAFETY LOCKED MASK=%03X ADC=%u PC4=%u,%u,%u Q=%02X ERR=%lu PC5=%u,%u,%u Q=%02X ERR=%lu SD=%u MOE=%u FOC=%u\r\n",
                (unsigned int)missing, (unsigned int)adc_ready,
                pc4.raw[0], pc4.raw[1], pc4.raw[2], (unsigned int)pc4_reasons,
                (unsigned long)pc4.failures,
                pc5.raw[0], pc5.raw[1], pc5.raw[2], (unsigned int)pc5_reasons,
                (unsigned long)pc5.failures,
                (unsigned int)(HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) == GPIO_PIN_SET),
                (unsigned int)((htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U),
                (unsigned int)foc_enable);
            UART_SendString(msg);
        }
        SafetyLocked_ForceOff();
        vTaskDelay(pdMS_TO_TICKS(95U));
    }
}
