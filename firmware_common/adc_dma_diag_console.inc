/* Included only by the ZERO_RETEST_BOOT service. Local UART, never Router RPC. */
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
#include "adc_parallel_console.inc"
#elif defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
#include "adc_three_phase_console.inc"
#else
static void ZeroRetest_DmaFormat(uint32_t request_id)
{
    AdcDmaDiagStatus s;
    char message[300];
    AdcDmaDiag_Snapshot(&s);
    (void)Protocol_SendFormatted(message, sizeof(message),
        "%lu OK ADC_DMA LOCK=%u SD=%u MOE=%u CCER=%lu CEN=%u FOC=%lu "
        "STATE=%lu REASON=%lu NU=%lu NV=%lu IRQ=%lu,%lu MS=%lu ERR=%lu,%lu "
        "RESTORE=%lu RANGE=%u:%u,%u:%u CRC=%08lX CAP=%u\r\n",
        (unsigned long)request_id, ZeroRetest_Locked(),
        (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) != 0U,
        (TIM1->BDTR & TIM_BDTR_MOE) != 0U, (unsigned long)TIM1->CCER,
        (TIM1->CR1 & TIM_CR1_CEN) != 0U, (unsigned long)foc_control_count,
        (unsigned long)s.state, (unsigned long)s.reason,
        (unsigned long)s.count_u, (unsigned long)s.count_v,
        (unsigned long)s.irq_u, (unsigned long)s.irq_v, (unsigned long)s.elapsed_ms,
        (unsigned long)s.adc_error_u, (unsigned long)s.adc_error_v,
        (unsigned long)s.restored, s.min_u, s.max_u, s.min_v, s.max_v,
        (unsigned long)s.crc32, ADC_DMA_DIAG_PAIRS);
}

static uint8_t ZeroRetest_DmaCommand(uint32_t request_id, const char *cmd)
{
    if (strcmp(cmd, "ADC DMA STATUS") == 0) {
        ZeroRetest_DmaFormat(request_id);
        return 1U;
    }
    if (strcmp(cmd, "ADC DMA SAMPLE") == 0) {
        ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_DMA);
        return 1U;
    }
    if (strncmp(cmd, "ADC DMA READ ", 13U) == 0) {
        char *end;
        const char *value = cmd + 13U;
        unsigned long first = strtoul(value, &end, 10);
        if (!isdigit((unsigned char)*value) || *end || first >= ADC_DMA_DIAG_PAIRS ||
            first % 16U || zero_retest_running) {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ADC_DMA_READ_INDEX");
            return 1U;
        }
        char payload[16U * 8U + 1U], message[200];
        for (unsigned i = 0U; i < 16U; ++i) {
            uint16_t u, v;
            if (!AdcDmaDiag_Read((uint32_t)first + i, &u, &v)) {
                Protocol_SendError(request_id, PROTO_ERR_NOT_READY, "ADC_DMA_NOT_READY");
                return 1U;
            }
            (void)snprintf(payload + i * 8U, 9U, "%04X%04X", u, v);
        }
        (void)Protocol_SendFormatted(message, sizeof(message),
            "%lu OK ADC_DMA_DATA I=%lu N=16 UV=%s\r\n",
            (unsigned long)request_id, first, payload);
        return 1U;
    }
    if (AdcDmaDiag_Busy() && strcmp(cmd, "ZERO STATUS") != 0 &&
        strcmp(cmd, "FW STATUS") != 0 && strcmp(cmd, "ANALOG SAFE STATUS") != 0) {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "ADC_DMA_SAMPLING_ACTIVE");
        return 1U;
    }
    return 0U;
}
#endif
