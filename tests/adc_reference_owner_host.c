/* Reuse the exact bounded task/HAL/mailbox model and actual owner C. */
#define main LegacyOwnerEntry
#include "zero_adc_owner_host.c"
#undef main

int main(int argc, char **argv)
{
    assert(argc == 2);
    unsigned scenario = (unsigned)strtoul(argv[1], NULL, 10);
    current_task = (void *)OWNER_TASK; ZeroAdcOwner_Init();
    current_task = (void *)PROTOCOL_TASK;
    uint8_t kind = ZERO_ADC_ACQUIRE_REFERENCE_OFF;
    input_pc4 = 0U;
    switch (scenario) {
    case 100: break;
    case 101: input_pc4 = 49U; break;
    case 102: input_pc4 = 50U; break;
    case 103: input_pc4 = 590U; break;
    case 104: kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; input_pc4 = 590U; break;
    case 105: kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; break;
    case 106: kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; input_pc4 = 499U; break;
    case 107: kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; input_pc4 = 700U; break;
    case 108: kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; input_pc4 = 500U; break;
    case 109: kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; input_pc4 = 699U; break;
    case 110: kind = ZERO_ADC_ACQUIRE_DMA; break;
    case 111: kind = ZERO_ADC_ACQUIRE_ZERO; break;
    case 112: kind = 99U; break;
    case 113: analog_vdda_boot_mv = 0U; break;
    case 114: analog_vdda_boot_mv = 2999U; break;
    case 115: analog_vdda_boot_mv = 3601U; break;
    case 116: analog_vdda_boot_valid = 0U; break;
    case 117: live_rc = HAL_ERROR; break;
    case 118: live_rc = HAL_TIMEOUT; break;
    case 119: live_rc = HAL_BUSY; break;
    case 120: input_pc4 = 4096U; break;
    case 121: input_pc5 = 4096U; break;
    case 122: locked = 0U; break;
    case 123: adc_fault = 1U; break;
    case 124: TIM1->CR1 = TIM_CR1_CEN; break;
    case 125: trial = 1U; break;
    case 126: fw_update.active = 1U; break;
    case 127: parallel_ready = 0U; break;
    case 128: clock_ok = 0U; break;
    case 129: zero_retest_interlock_fault = 1U; break;
    case 130: zero_retest_adc_ready = 0U; break;
    case 131: lose_during_sample = 2U; break;
    case 132: lose_during_sample = 1U; break;
    case 133: lose_during_sample = 3U; break;
    case 134: fail_start = 1U; break;
    case 135: case 136: case 137: break;
    case 138: fail_reply_send = 1U; break;
    case 139: corrupt_reply = 1U; break;
    case 140:
        current_task = (void *)OWNER_TASK;
        ZeroRetest_SubmitAcquisition(777U, kind);
        assert(!live_calls && strstr(output, "OWNER_UNAVAILABLE")); return 0;
    case 141: {
        ZeroAdcRequest occupied = {123U, kind};
        assert(xQueueSend(zero_adc_requests, &occupied, 0U) == pdPASS);
        ZeroRetest_SubmitAcquisition(777U, kind);
        assert(!live_calls && strstr(output, "OWNER_UNAVAILABLE")); return 0;
    }
    case 142: analog_vdda_boot_mv = 3000U; break;
    case 143: analog_vdda_boot_mv = 3600U; break;
    default: assert(0);
    }
    ZeroRetest_SubmitAcquisition(777U, kind);
    if (scenario == 100U || scenario == 101U || scenario == 104U || scenario == 108U ||
        scenario == 109U || (scenario >= 135U && scenario <= 137U) || scenario >= 142U) {
        assert(live_calls == 1U && dma_calls == 1U && dma_replies == 1U && !output[0]);
        assert(!zero_replies && !zero_retest_attempted && !zero_retest_running);
        assert(zero_reference_power_kind == kind);
        assert(zero_reference_admit_mv == ((uint32_t)input_pc4 * analog_vdda_boot_mv * 25U + 2047U) / 4095U);
        if (scenario >= 135U && scenario <= 137U) {
            uint32_t first_mv = zero_reference_admit_mv;
            if (scenario != 136U) { dma_busy = 0U; TIM1->CR1 = 0U; }
            if (scenario == 137U) { kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; input_pc4 = 590U; }
            ZeroRetest_SubmitAcquisition(778U, kind);
            assert(dma_replies == 1U && zero_reference_power_kind == ZERO_ADC_ACQUIRE_REFERENCE_OFF);
            assert(zero_reference_admit_mv == first_mv);
            assert(strstr(output, scenario == 136U ? "NOT_ADMITTED" : "ONESHOT_OR_CONFIG"));
        }
    } else if (scenario == 138U || scenario == 139U) {
        assert(strstr(output, "REPLY_MISMATCH"));
        if (scenario == 138U) assert(fatal_calls == 1U && stop_calls == 1U && !TIM1->CR1);
    } else {
        assert(!dma_replies && !zero_replies && !zero_reference_power_kind && !zero_reference_admit_mv);
        assert(!zero_retest_attempted && !zero_retest_running && output[0]);
        if (scenario == 134U) assert(dma_calls == 1U && strstr(output, "ONESHOT_OR_CONFIG"));
        else assert(!dma_calls);
        if (scenario >= 110U && scenario <= 112U) assert(!live_calls);
        if (scenario >= 122U && scenario <= 130U) assert(!live_calls);
        if (scenario == 102U || scenario == 103U) assert(strstr(output, "REQUIRES_12V_OFF"));
        if (scenario >= 105U && scenario <= 107U) assert(strstr(output, "REQUIRES_12V_ON"));
    }
    assert(!primask);
    printf("REFERENCE OWNER scenario %u PASS\n", scenario);
    return 0;
}
