/* Hard-off, local UART only. Separate names prevent a legacy UV reader from
 * treating a three-channel capture as two-channel data. */
static void ZeroRetest_DmaFormat(uint32_t request_id)
{
    AdcDmaDiagStatus s;
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
    char message[560]; /* Extra diagnostic pin-policy fields; normal profile unchanged. */
#else
    char message[480];
#endif
    AdcDmaDiag_Snapshot(&s);
    (void)Protocol_SendFormatted(message, sizeof(message),
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
        "%lu OK ADC3PAR MODE=ADC12_REFERENCE CAPTURE_MASK=3 CH=2 REAL_W=0 PAD_W=ZERO_UNSAMPLED W_ADC=5 W_PIN=PA8 W_DELAY=NONE SYNC=COMMON_EVENT W_READY=%u LOCK=%u SD=%u MOE=%u CCER=%lu "
#elif defined(ADC_DMA_PA1_ONLY_DIAGNOSTIC)
        "%lu OK ADC3PAR MODE=PA1_ONLY CAPTURE_MASK=2 CH=1 REAL_W=0 PAD_UW=ZERO_UNSAMPLED W_ADC=5 W_PIN=PA8 W_DELAY=NONE SYNC=SINGLE W_READY=%u LOCK=%u SD=%u MOE=%u CCER=%lu "
#elif defined(ADC_DMA_ADC12_ONLY_DIAGNOSTIC)
        "%lu OK ADC3PAR MODE=ADC12_ONLY CAPTURE_MASK=3 CH=2 REAL_W=0 PAD_W=ZERO_UNSAMPLED W_ADC=5 W_PIN=PA8 W_DELAY=NONE SYNC=COMMON_EVENT W_READY=%u LOCK=%u SD=%u MOE=%u CCER=%lu "
#else
        "%lu OK ADC3PAR CH=3 REAL_W=1 W_ADC=5 W_PIN=PA8 W_DELAY=NONE SYNC=COMMON_EVENT W_READY=%u LOCK=%u SD=%u MOE=%u CCER=%lu "
#endif
        "CEN=%u FOC=%lu STATE=%lu REASON=%lu NU=%lu NV=%lu NW=%lu "
        "IRQ=%lu,%lu,%lu MS=%lu ERR=%lu,%lu,%lu RESTORE=%lu "
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
        "SMP_CYCLES=247.5 SMP_CHECK=%lu "
#endif
        "RANGE=%u:%u,%u:%u,%u:%u CRC=%08lX CAP=%u"
#if defined(ADC_DMA_REFERENCE_DOUBLE_CAPTURE)
        " WINDOW=DOUBLE RAW_STORAGE=UV_ONLY"
#endif
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
        " SUPPLY_POLICY=EXPLICIT_OFF_ON POWER=%s ADMIT_MV=%lu"
#endif
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
        " PIN_POLICY=GPIO_LOW PIN_CFG=%u PIN_LEVEL=%u"
#endif
        "\r\n",
        (unsigned long)request_id, AdcDmaDiag_ParallelReady(), ZeroRetest_Locked(),
        (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) != 0U,
        (TIM1->BDTR & TIM_BDTR_MOE) != 0U, (unsigned long)TIM1->CCER,
        (TIM1->CR1 & TIM_CR1_CEN) != 0U, (unsigned long)foc_control_count,
        (unsigned long)s.state, (unsigned long)s.reason,
        (unsigned long)s.count_u, (unsigned long)s.count_v, (unsigned long)s.count_w,
        (unsigned long)s.irq_u, (unsigned long)s.irq_v, (unsigned long)s.irq_w, (unsigned long)s.elapsed_ms,
        (unsigned long)s.adc_error_u, (unsigned long)s.adc_error_v, (unsigned long)s.adc_error_w,
        (unsigned long)s.restored,
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
        (unsigned long)s.sampling_checked_mask,
#endif
        s.min_u, s.max_u, s.min_v, s.max_v, s.min_w, s.max_w,
        (unsigned long)s.crc32, ADC_DMA_DIAG_PAIRS
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
        , zero_reference_power_kind == ZERO_ADC_ACQUIRE_REFERENCE_OFF ? "OFF" :
          (zero_reference_power_kind == ZERO_ADC_ACQUIRE_REFERENCE_ON ? "ON" : "NONE"),
        (unsigned long)zero_reference_admit_mv
#endif
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
        , AdcControlPins_ConfigLow(), AdcControlPins_LevelLow()
#endif
        );
}

static uint8_t ZeroRetest_DmaCommand(uint32_t request_id, const char *cmd)
{
    if (strcmp(cmd, "ADC PAR STATUS") == 0) {
        ZeroRetest_DmaFormat(request_id);
        return 1U;
    }
    if (strcmp(cmd, "ADC PAR SAMPLE") == 0) {
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ADC3PAR_REFERENCE_SELECT_POWER_OFF_OR_ON");
#else
        ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_DMA);
#endif
        return 1U;
    }
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
    if (strcmp(cmd, "ADC PAR SAMPLE OFF") == 0 || strcmp(cmd, "ADC PAR SAMPLE ON") == 0) {
        ZeroRetest_SubmitAcquisition(request_id, strcmp(cmd, "ADC PAR SAMPLE OFF") == 0 ?
            ZERO_ADC_ACQUIRE_REFERENCE_OFF : ZERO_ADC_ACQUIRE_REFERENCE_ON);
        return 1U;
    }
#endif
    if (strncmp(cmd, "ADC PAR READ ", 13U) == 0) {
        const char *value = cmd + 13U;
        char *end;
        unsigned long first = strtoul(value, &end, 10);
        if (!isdigit((unsigned char)*value) || *end || first >= ADC_DMA_DIAG_PAIRS ||
            first % 8U || zero_retest_running) {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ADC3PAR_READ_INDEX");
            return 1U;
        }
        char payload[8U * 12U + 1U], message[180];
        for (unsigned i = 0U; i < 8U; ++i) {
            uint16_t u, v, w;
            if (!AdcDmaDiag_ReadThreePhase((uint32_t)first + i, &u, &v, &w)) {
                Protocol_SendError(request_id, PROTO_ERR_NOT_READY, "ADC3PAR_NOT_READY");
                return 1U;
            }
            (void)snprintf(payload + i * 12U, 13U, "%04X%04X%04X", u, v, w);
        }
        (void)Protocol_SendFormatted(message, sizeof(message),
            "%lu OK ADC3PAR_DATA I=%lu N=8 UVW=%s\r\n",
            (unsigned long)request_id, first, payload);
        return 1U;
    }
    if (strncmp(cmd, "ADC DMA ", 8U) == 0 || strncmp(cmd, "ADC 3PH ", 8U) == 0) {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ADC3PAR_USE_THREE_CHANNEL_COMMANDS");
        return 1U;
    }
    if (AdcDmaDiag_Busy() && strcmp(cmd, "ZERO STATUS") != 0 &&
        strcmp(cmd, "FW STATUS") != 0 && strcmp(cmd, "ANALOG SAFE STATUS") != 0) {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "ADC3PAR_SAMPLING_ACTIVE");
        return 1U;
    }
    return 0U;
}
