/* Standalone zero-only service profile, not motor-control qualification.
 * Both slots must run this profile before powered analog diagnosis resumes.
 * No motor/encoder/Modbus/network tasks, KVS writes, or software unlock.
 * Service auto-confirm requires 5 s of hard-off outputs plus fresh local
 * console requests. It says nothing about current-zero quality or FOC health.
 */
#include "foc_current_zero.h"
static FocZeroCal zero_retest_cal;
#if defined(FOC_OC_LAYERED_SELFTEST)
#include "foc_protection_selftest.h"
static FocProtectionSelftestResult oc_layers_result;
static uint8_t oc_layers_done;
#endif
#if defined(ZERO_MEDIAN_DIAGNOSTIC)
#include "foc_zero_median.h"
#include "foc_current_median.h"
static FocZeroMedian zero_median;
#endif
#if defined(FOC_ZERO_FAILURE_TRACE)
#include "foc_zero_failure_trace.h"
static FocZeroFailureTrace zero_trace;
#endif
static volatile uint8_t zero_retest_running, zero_retest_attempted;
static volatile uint8_t zero_retest_interlock_fault;
static volatile uint32_t zero_retest_heartbeats, zero_retest_last_request;
static uint32_t zero_retest_started_ms;
static uint8_t zero_retest_adc_ready;

static uint8_t ZeroRetest_Locked(void)
{
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
    if (!AdcControlPins_ConfigLow() || !AdcControlPins_LevelLow()) return 0U;
#endif
    return analog_safe_latched && !foc_enable &&
        !(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) &&
        !(TIM1->BDTR & (TIM_BDTR_MOE | TIM_BDTR_AOE)) && !TIM1->CCER;
}

static void ZeroRetest_Off(void)
{
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
    AdcControlPins_HoldLow(); /* No reconfiguration: a mode fault remains observable. */
#endif
    foc_enable = 0U;
    foc_id_ref_A = foc_iq_ref_A = 0.0f;
    analog_safe_latched = 1U;
}

static void ZeroRetest_Stop(void)
{
    TIM1->CR1 &= ~TIM_CR1_CEN;
    ZeroRetest_Off();
    zero_retest_running = 0U;
#if defined(FOC_ZERO_FAILURE_TRACE)
    if (zero_retest_attempted) FocTrace_Freeze(&zero_trace);
#endif
}

#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
#include "switch_feedback_diag.inc"
#endif

static void ZeroRetest_InjectedPair(void)
{
    uint16_t u = (uint16_t)HAL_ADCEx_InjectedGetValue(&hadc1, ADC_INJECTED_RANK_1);
    uint16_t v = (uint16_t)HAL_ADCEx_InjectedGetValue(&hadc2, ADC_INJECTED_RANK_1);
    uint8_t pair_ready = (hadc2.Instance->ISR & ADC_FLAG_JEOS) != 0U;
    __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
    if (switch_active) { SwitchFeedback_InjectedPair(u, v, pair_ready); return; }
#endif
    if (!zero_retest_running) return;
    ++injected_seq_count;
    if (!ZeroRetest_Locked() || !pair_ready || adc_fault) {
        FocZero_Abort(&zero_retest_cal, !ZeroRetest_Locked() ? FOC_ZERO_UNSAFE : FOC_ZERO_RATE);
        zero_retest_interlock_fault |= !ZeroRetest_Locked();
        ZeroRetest_Stop();
        return;
    }
#if defined(ZERO_MEDIAN_DIAGNOSTIC)
#if defined(FOC_ZERO_FAILURE_TRACE)
    FocTrace_Push(&zero_trace, &zero_median, &zero_retest_cal, u, v);
    if (!zero_trace.done) return; /* <=16 raw-only post pairs; outputs hard off. */
#else
    FocZeroMedian_Push(&zero_median, &zero_retest_cal, u, v);
#endif
#else
    FocZero_Push(&zero_retest_cal, u, v); /* No filtering or FOC call. */
#endif
    if (zero_retest_cal.state == FOC_ZERO_READY || zero_retest_cal.state == FOC_ZERO_FAILED)
        ZeroRetest_Stop();
}

static void ZeroRetest_Format(uint32_t request_id)
{
    FocZeroCal c;
    char message[400];
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    FocZero_Snapshot(&zero_retest_cal, &c);
    __set_PRIMASK(mask);
    (void)Protocol_SendFormatted(message, sizeof(message),
        "%lu OK ZERO PROFILE=LOCKED_DIAGNOSTIC "
#if defined(ZERO_MEDIAN_DIAGNOSTIC)
        FOC_CURRENT_FILTER_FIELDS
#endif
        "ADC_OWNER=1 LOCK=%u SD=%u MOE=%u CCER=%lu CEN=%u "
        "FOC=%lu MOTOR_READY=0 IF=%u ADC_READY=%u ACTIVE=%u STATE=%u REASON=%u "
        "SPAN=%u NOM=%u U0=%u V0=%u N=%lu SET=%lu RET=%lu S=%lu D=%lu "
        "RNG=%u:%u,%u:%u RAW=%u:%u,%u:%u ADC=%lu HB=%lu\r\n",
        (unsigned long)request_id, ZeroRetest_Locked(),
        (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) != 0U,
        (TIM1->BDTR & TIM_BDTR_MOE) != 0U, (unsigned long)TIM1->CCER,
        (TIM1->CR1 & TIM_CR1_CEN) != 0U, (unsigned long)foc_control_count,
        zero_retest_interlock_fault, zero_retest_adc_ready, zero_retest_running,
        (unsigned)c.state, (unsigned)c.reason, (unsigned)FOC_ZERO_MAX_SPAN,
        c.nominal, c.zero_u, c.zero_v,
        (unsigned long)c.count, (unsigned long)c.settled, (unsigned long)c.restarts,
        (unsigned long)c.span_restarts, (unsigned long)c.drift_restarts,
        c.min_u, c.max_u, c.min_v, c.max_v, c.observed_min_u, c.observed_max_u,
        c.observed_min_v, c.observed_max_v, (unsigned long)injected_seq_count,
        (unsigned long)zero_retest_heartbeats);
}

#include "zero_adc_owner.inc"

#if defined(ZERO_MEDIAN_DIAGNOSTIC)
static void ZeroMedian_Format(uint32_t request_id)
{
    FocZeroMedian m;
    FocZeroCal c;
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    m = zero_median;
    c = zero_retest_cal;
    __set_PRIMASK(mask);
    char message[400];
    (void)Protocol_SendFormatted(message, sizeof(message),
        "%lu OK ZERO_FILTER " FOC_CURRENT_FILTER_FIELDS "MOTOR_READY=0 PAIRS=%lu CHANGED=%lu OUT=%lu "
        "RAW_STATE=%u RAW_REASON=%u RAW_N=%lu RAW_U0=%u RAW_V0=%u "
        "RAW_LAST=%u,%u RAW_RANGE=%u:%u,%u:%u FILTER_STATE=%u FILTER_REASON=%u RAW_WINDOW=%lu\r\n",
        (unsigned long)request_id, (unsigned long)m.pairs, (unsigned long)m.changed,
        (unsigned long)m.outside_nominal, (unsigned)m.raw.state, (unsigned)m.raw.reason,
        (unsigned long)m.raw.count, m.raw.zero_u, m.raw.zero_v,
        m.raw.last_u, m.raw.last_v, m.min_u, m.max_u, m.min_v, m.max_v,
        (unsigned)c.state, (unsigned)c.reason, (unsigned long)m.raw_window_pairs);
}
#endif

#if defined(ADC_DMA_RAW_DIAGNOSTIC)
#include "adc_dma_diag_console.inc"
#endif
#if defined(FOC_ZERO_FAILURE_TRACE)
#include "zero_failure_trace_console.inc"
#endif

static uint8_t ZeroRetest_HandleCommand(uint32_t request_id, const char *cmd)
{
    /* Even maintenance/IAP is local-only; no routed console admission. */
    if (!protocol_esp_ping_uart_local) {
        Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ZERO_LOCAL_UART_ONLY");
        return 1U;
    }
#if defined(FOC_OC_LAYERED_SELFTEST)
    if (strcmp(cmd, "OC LAYERS SELFTEST") == 0) {
        char message[224];
        (void)Protocol_SendFormatted(message, sizeof(message),
            "%lu OK OC_LAYERS INPUT=SYNTHETIC DONE=%u CASES=%lu CHECKS=%lu FAIL=0x%08lX "
            "SOFT_MA=4000 HARD_SIM_MA=5000 ACTUAL_LIMIT_MA=4000 LOCK=%u MOTOR_QUALIFIED=0\r\n",
            (unsigned long)request_id, oc_layers_done, (unsigned long)oc_layers_result.cases,
            (unsigned long)oc_layers_result.checks, (unsigned long)oc_layers_result.failures,
            ZeroRetest_Locked());
        return 1U;
    }
#endif
#if defined(FOC_ZERO_FAILURE_TRACE)
    if (ZeroTrace_Command(request_id, cmd)) return 1U;
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
    if (SwitchFeedback_Command(request_id, cmd)) return 1U;
#endif
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    if (ZeroRetest_DmaCommand(request_id, cmd)) return 1U;
#endif
    if (strcmp(cmd, "ZERO STATUS") == 0) {
        ++zero_retest_heartbeats;
        zero_retest_last_request = HAL_GetTick();
        ZeroRetest_Format(request_id);
        return 1U;
    }
#if defined(ZERO_MEDIAN_DIAGNOSTIC)
    if (strcmp(cmd, "ZERO FILTER STATUS") == 0) {
        ZeroMedian_Format(request_id);
        return 1U;
    }
#endif
    if (strcmp(cmd, "ZERO SAMPLE") == 0) {
#if defined(FOC_OC_LAYERED_SELFTEST)
        Protocol_SendError(request_id, PROTO_ERR_NOT_READY, "SYNTHETIC_SELFTEST_ONLY_NO_ACQUISITION");
        return 1U;
#endif
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        /* The older zero qualifier only measures U/V. It must not claim a
         * qualified three-phase zero or publish a fabricated W reference. */
        Protocol_SendError(request_id, PROTO_ERR_NOT_READY, "ADC3PH_RAW_ONLY_NO_ZERO_PUBLICATION");
        return 1U;
#endif
        ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_ZERO);
        return 1U;
    }
    if (zero_retest_running && strcmp(cmd, "FW STATUS") != 0 &&
        strcmp(cmd, "ANALOG SAFE STATUS") != 0) {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "ZERO_SAMPLING_ACTIVE");
        return 1U;
    }
    if (strcmp(cmd, "FW STATUS") == 0 || strcmp(cmd, "ANALOG SAFE STATUS") == 0 ||
        strcmp(cmd, "STATUS") == 0 || strcmp(cmd, "SELFTEST STATUS") == 0 ||
        strcmp(cmd, "ANALOG VOLT") == 0 || strcmp(cmd, "ANALOG LIVE") == 0 ||
        strncmp(cmd, "FW BEGIN ", 9U) == 0 || strcmp(cmd, "FW END") == 0 ||
        strncmp(cmd, "XFER ENGINE ", 12U) == 0)
        return 0U;
    Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "ZERO_DIAGNOSTIC_COMMAND_ONLY");
    return 1U; /* No START/CLEAR/BOOT/CONFIRM/Modbus/parameter/RPC admission. */
}

static void __attribute__((noreturn)) ZeroRetest_RunForever(void)
{
    uint32_t stable = 0U, elapsed = 0U, last_health = HAL_GetTick();
    uint32_t last_analog = 0U;
    ZeroRetest_Stop();
#if defined(FOC_OC_LAYERED_SELFTEST)
    if (ZeroRetest_Locked() && !(TIM1->CR1 & TIM_CR1_CEN)) {
        oc_layers_result = FocProtectionSelftest_Run();
        oc_layers_done = 1U;
    }
    if (!oc_layers_done || oc_layers_result.failures || !ZeroRetest_Locked())
        zero_retest_interlock_fault = 1U;
    UART_SendLiteral("OC LAYERS SELFTEST: INPUT=SYNTHETIC; 5A boundary simulated ONLY; actual 4A unchanged; no motion\r\n");
#endif
    UART_SendLiteral("ZERO RETEST: hard-locked diagnostic service; motor NOT qualified; no auto sampling\r\n");
    zero_retest_adc_ready = HAL_ADCEx_Calibration_Start(&hadc1, ADC_SINGLE_ENDED) == HAL_OK &&
        HAL_ADCEx_Calibration_Start(&hadc2, ADC_SINGLE_ENDED) == HAL_OK;
    ADC_AnalogBootSnapshot();
    ADC_VrefBootSnapshot();
    zero_retest_adc_ready &= ADC_ConfigIndependentSameTrigger() == HAL_OK;
    TIM1->DIER &= ~(TIM_DIER_UIE | TIM_DIER_CC4IE);
    zero_retest_adc_ready &= HAL_ADCEx_InjectedStart(&hadc2) == HAL_OK &&
        HAL_ADCEx_InjectedStart_IT(&hadc1) == HAL_OK;
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    AdcDmaDiag_Init(&hadc1, &hadc2, ZeroRetest_Locked);
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
    zero_retest_adc_ready &= AdcDmaDiag_ParallelReady();
#endif
#endif
    ZeroAdcOwner_Init(); /* Bind ADC2 before ProtocolTask can submit a request. */
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
    SwitchFeedback_Init();
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
    UART_SendLiteral("FILTERED BRIDGE DIAGNOSTIC: DISCONNECTED_50MS; 25us guard; no motor control\r\n");
#else
    UART_SendLiteral("SWITCH DIAGNOSTIC: OPEN_LOAD_ONLY; local explicit stages; 180ms capture/190ms TIM7 guard; no motor control\r\n");
#endif
#endif
    if (UART_Async_Init(&hlpuart1) != HAL_OK || UART_RxDma_Init(&hlpuart1) != HAL_OK ||
        !Router_Init(ROUTER_LOCAL_NODE_ID)) Error_Handler();
    Router_RegisterPortTx(ROUTER_PORT_UART1, Router_Uart1Tx);
    protocol_async_event_queue = xQueueCreate(PROTOCOL_ASYNC_EVENT_QUEUE_DEPTH,
                                             sizeof(ProtocolAsyncEvent_t));
    if (!protocol_async_event_queue ||
        xTaskCreate(RouterTask, "ZeroRouter", 1024U, NULL, 2U, NULL) != pdPASS ||
        xTaskCreate(ProtocolTask, "ZeroProto", 1024U, NULL, 2U, NULL) != pdPASS)
        Error_Handler();
    g_uart_async_runtime_enable = 1U;
#if defined(UART_FIRMWARE_TRANSFER)
    PW_UartFirmwareTransfer_Init();
#endif
    /* No KVS load/migration, motor task, encoder task, or normal BootHealthTask. */
    for (;;) {
        uint32_t now = HAL_GetTick();
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
        SwitchFeedback_Service();
        if (switch_active) {
            vTaskDelay(pdMS_TO_TICKS(1U));
            continue; /* No background ADC2 reconfiguration or zero lock overwrite. */
        }
#endif
        if (!ZeroRetest_Locked()) {
            zero_retest_interlock_fault = 1U;
            FocZero_Abort(&zero_retest_cal, FOC_ZERO_UNSAFE);
            ZeroRetest_Stop();
        }
        ZeroRetest_Off();
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
        AdcDmaDiag_Service(now);
        AdcDmaDiagStatus dma_status;
        AdcDmaDiag_Snapshot(&dma_status);
        if (dma_status.state == ADC_DMA_DIAG_FAILED) adc_fault = 1U;
        ZeroAdcOwner_Service();
        if (AdcDmaDiag_Busy()) {
            vTaskDelay(pdMS_TO_TICKS(1U));
            continue; /* No background PC4/PC5 reconfiguration during capture. */
        }
#else
        ZeroAdcOwner_Service();
#endif
        now = HAL_GetTick(); /* Request handling may have advanced the tick. */
        if (zero_retest_running && (uint32_t)(now - zero_retest_started_ms) >= FOC_ZERO_TIMEOUT_MS) {
            uint32_t mask = __get_PRIMASK();
            __disable_irq();
            FocZero_Abort(&zero_retest_cal, FOC_ZERO_TIMEOUT);
            ZeroRetest_Stop();
            __set_PRIMASK(mask);
        }
        if (!zero_retest_running && !fw_update.active && (uint32_t)(now - last_analog) >= 100U) {
            last_analog = now;
            (void)ZeroAdcOwner_LiveSample();
        }
        if (BootHealth_IsCurrentTrial() && (uint32_t)(now - last_health) >= 500U) {
            last_health = now;
            elapsed += 500U;
            uint8_t healthy = !zero_retest_interlock_fault && ZeroRetest_Locked() &&
                !(TIM1->CR1 & TIM_CR1_CEN) && !foc_control_count &&
                UART_Async_IsReady() && zero_retest_heartbeats >= 2U &&
                (uint32_t)(now - zero_retest_last_request) < 1500U;
#if defined(FOC_OC_LAYERED_SELFTEST)
            healthy &= oc_layers_done && !oc_layers_result.failures;
#endif
            stable = healthy ? stable + 500U : 0U;
            if (stable >= 5000U || elapsed >= 12000U) {
                ZeroRetest_Stop();
                if (stable >= 5000U) {
                    UART_SendLiteral("ZERO SERVICE HEALTH PASS: output lock + local UART ONLY; NOT zero/FOC pass\r\n");
                    if (!BootMeta_ConfirmCurrent()) Error_Handler();
                } else {
                    UART_SendLiteral("ZERO SERVICE HEALTH FAIL: unconfirmed; normal rollback\r\n");
                }
                vTaskDelay(pdMS_TO_TICKS(150U));
                NVIC_SystemReset();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10U));
    }
}
