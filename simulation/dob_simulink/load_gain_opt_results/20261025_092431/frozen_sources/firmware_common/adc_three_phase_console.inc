/* Hard-off, local UART only. Separate names prevent a legacy UV reader from
 * treating a three-channel capture as two-channel data. */
static void ZeroRetest_DmaFormat(uint32_t request_id)
{
    AdcDmaDiagStatus s;
    char message[380];
    AdcDmaDiag_Snapshot(&s);
    (void)Protocol_SendFormatted(message, sizeof(message),
        "%lu OK ADC3PH CH=3 REAL_W=1 W_DELAY=SEQ LOCK=%u SD=%u MOE=%u CCER=%lu "
        "CEN=%u FOC=%lu STATE=%lu REASON=%lu NU=%lu NV=%lu NW=%lu "
        "IRQ=%lu,%lu MS=%lu ERR=%lu,%lu RESTORE=%lu "
        "RANGE=%u:%u,%u:%u,%u:%u CRC=%08lX CAP=%u\r\n",
        (unsigned long)request_id, ZeroRetest_Locked(),
        (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) != 0U,
        (TIM1->BDTR & TIM_BDTR_MOE) != 0U, (unsigned long)TIM1->CCER,
        (TIM1->CR1 & TIM_CR1_CEN) != 0U, (unsigned long)foc_control_count,
        (unsigned long)s.state, (unsigned long)s.reason,
        (unsigned long)s.count_u, (unsigned long)s.count_v, (unsigned long)s.count_w,
        (unsigned long)s.irq_u, (unsigned long)s.irq_v, (unsigned long)s.elapsed_ms,
        (unsigned long)s.adc_error_u, (unsigned long)s.adc_error_v,
        (unsigned long)s.restored, s.min_u, s.max_u, s.min_v, s.max_v, s.min_w, s.max_w,
        (unsigned long)s.crc32, ADC_DMA_DIAG_PAIRS);
}

static uint8_t ZeroRetest_DmaCommand(uint32_t request_id, const char *cmd)
{
    if (strcmp(cmd, "ADC 3PH STATUS") == 0) {
        ZeroRetest_DmaFormat(request_id);
        return 1U;
    }
    if (strcmp(cmd, "ADC 3PH SAMPLE") == 0) {
        ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_DMA);
        return 1U;
    }
    if (strncmp(cmd, "ADC 3PH READ ", 13U) == 0) {
        const char *value = cmd + 13U;
        char *end;
        unsigned long first = strtoul(value, &end, 10);
        if (!isdigit((unsigned char)*value) || *end || first >= ADC_DMA_DIAG_PAIRS ||
            first % 8U || zero_retest_running) {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ADC3PH_READ_INDEX");
            return 1U;
        }
        char payload[8U * 12U + 1U], message[180];
        for (unsigned i = 0U; i < 8U; ++i) {
            uint16_t u, v, w;
            if (!AdcDmaDiag_ReadThreePhase((uint32_t)first + i, &u, &v, &w)) {
                Protocol_SendError(request_id, PROTO_ERR_NOT_READY, "ADC3PH_NOT_READY");
                return 1U;
            }
            (void)snprintf(payload + i * 12U, 13U, "%04X%04X%04X", u, v, w);
        }
        (void)Protocol_SendFormatted(message, sizeof(message),
            "%lu OK ADC3PH_DATA I=%lu N=8 UVW=%s\r\n",
            (unsigned long)request_id, first, payload);
        return 1U;
    }
    if (strncmp(cmd, "ADC DMA ", 8U) == 0) {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ADC3PH_USE_THREE_CHANNEL_COMMANDS");
        return 1U;
    }
    if (AdcDmaDiag_Busy() && strcmp(cmd, "ZERO STATUS") != 0 &&
        strcmp(cmd, "FW STATUS") != 0 && strcmp(cmd, "ANALOG SAFE STATUS") != 0) {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "ADC3PH_SAMPLING_ACTIVE");
        return 1U;
    }
    return 0U;
}
