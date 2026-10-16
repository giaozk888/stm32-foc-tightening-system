/* Only the locked service task may measure ADC2 or hand it over to DMA.
 * ProtocolTask waits for a copied reply, so its local reply-route context is
 * retained; the owner never sends protocol replies from another task.
 * No long interrupt mask around HAL polling and no cached-voltage admission.
 */
enum { ZERO_ADC_ACQUIRE_ZERO, ZERO_ADC_ACQUIRE_DMA,
       ZERO_ADC_ACQUIRE_REFERENCE_OFF, ZERO_ADC_ACQUIRE_REFERENCE_ON };
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
#if !defined(ZERO_RETEST_BOOT) || !defined(ADC_DMA_RAW_DIAGNOSTIC) || \
    !defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC) || !defined(ADC_DMA_PARALLEL_DIAGNOSTIC) || \
    !defined(ADC_DMA_PARALLEL_LONG_SAMPLE) || !defined(ADC_DMA_ADC12_ONLY_DIAGNOSTIC)
#error "Reference input capture requires the standalone hard-off ADC1/2 long-sample profile"
#endif
/* Admission record, not a fabricated supply value. Updated only on a start. */
static uint8_t zero_reference_power_kind;
static uint32_t zero_reference_admit_mv;
#endif

static uint8_t ZeroAdcOwner_DmaKind(uint8_t kind)
{
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
    return kind == ZERO_ADC_ACQUIRE_REFERENCE_OFF || kind == ZERO_ADC_ACQUIRE_REFERENCE_ON;
#else
    return kind == ZERO_ADC_ACQUIRE_DMA;
#endif
}
typedef struct {
    uint32_t request_id;
    uint8_t kind;
} ZeroAdcRequest;
typedef struct {
    uint32_t request_id, bus_mv, tick_ms;
    uint16_t pc4_raw, pc5_raw, vdda_mv;
    uint8_t kind, supply_attempted, supply_valid, sample_rc;
    ProtocolError_t error_code;
    const char *error_name;
} ZeroAdcReply;
static TaskHandle_t zero_adc_owner_task;
static QueueHandle_t zero_adc_requests, zero_adc_replies;
static StaticQueue_t zero_adc_request_control, zero_adc_reply_control;
static uint8_t zero_adc_request_storage[sizeof(ZeroAdcRequest)];
static uint8_t zero_adc_reply_storage[sizeof(ZeroAdcReply)];

#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
#define ZERO_ADC_DMA_PREFIX "ADC3PAR"
#elif defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
#define ZERO_ADC_DMA_PREFIX "ADC3PH"
#else
#define ZERO_ADC_DMA_PREFIX "ADC_DMA"
#endif
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
static void ZeroRetest_DmaFormat(uint32_t request_id);
#endif

static void ZeroAdcOwner_Init(void)
{
    zero_adc_owner_task = xTaskGetCurrentTaskHandle();
    zero_adc_requests = xQueueCreateStatic(1U, sizeof(ZeroAdcRequest),
        zero_adc_request_storage, &zero_adc_request_control);
    zero_adc_replies = xQueueCreateStatic(1U, sizeof(ZeroAdcReply),
        zero_adc_reply_storage, &zero_adc_reply_control);
    if (!zero_adc_owner_task || !zero_adc_requests || !zero_adc_replies)
        Error_Handler();
}

static HAL_StatusTypeDef ZeroAdcOwner_LiveSample(void)
{
    if (!zero_adc_owner_task || xTaskGetCurrentTaskHandle() != zero_adc_owner_task)
        return HAL_ERROR;
    if (zero_retest_running || (TIM1->CR1 & TIM_CR1_CEN)) return HAL_BUSY;
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    if (AdcDmaDiag_Busy()) return HAL_BUSY;
#endif
    return ADC_AnalogLiveSample();
}

static uint8_t ZeroAdcOwner_Admitted(uint8_t kind)
{
    if (BootHealth_IsCurrentTrial() || fw_update.active || zero_retest_running ||
        zero_retest_interlock_fault || !ZeroRetest_Locked() || !zero_retest_adc_ready ||
        adc_fault || !FocAdcClock_IsExpected() || (TIM1->CR1 & TIM_CR1_CEN)) return 0U;
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    if (AdcDmaDiag_Busy()) return 0U;
#endif
    if (kind == ZERO_ADC_ACQUIRE_ZERO) {
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        return 0U;
#else
        return !zero_retest_attempted;
#endif
    }
    if (!ZeroAdcOwner_DmaKind(kind)) return 0U;
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
    return AdcDmaDiag_ParallelReady();
#elif defined(ADC_DMA_RAW_DIAGNOSTIC)
    return 1U;
#else
    return 0U;
#endif
}

static void ZeroAdcOwner_Service(void)
{
    ZeroAdcRequest request;
    ZeroAdcReply reply = {0};
    if (!zero_adc_owner_task || xTaskGetCurrentTaskHandle() != zero_adc_owner_task)
        return;
    if (xQueueReceive(zero_adc_requests, &request, 0U) != pdPASS) return;
    reply.request_id = request.request_id;
    reply.kind = request.kind;
    reply.sample_rc = UINT8_MAX; /* Distinguish not measured from HAL_OK. */
    reply.error_code = PROTO_ERR_NOT_READY;

    uint8_t admitted = ZeroAdcOwner_Admitted(request.kind);
    if (ZeroAdcOwner_DmaKind(request.kind)) {
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
        reply.error_name = ZERO_ADC_DMA_PREFIX "_NOT_ADMITTED";
#else
        reply.error_name = "ADC_DMA_PROFILE_DISABLED";
#endif
    } else if (request.kind == ZERO_ADC_ACQUIRE_ZERO) {
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        reply.error_name = "ADC3PH_RAW_ONLY_NO_ZERO_PUBLICATION";
#else
        reply.error_name = "ZERO_NOT_ADMITTED";
#endif
    } else {
        admitted = 0U;
        reply.error_name = "ZERO_ADC_BAD_OPERATION";
    }

    if (admitted) {
        reply.supply_attempted = 1U;
        reply.sample_rc = (uint8_t)ZeroAdcOwner_LiveSample();
        /* This task is the sole writer. Copy the same measurement before
         * any background refresh; the queued reply owns its snapshot. */
        if (reply.sample_rc == HAL_OK) {
            reply.pc4_raw = analog_live_pc4_raw;
            reply.pc5_raw = analog_live_pc5_raw;
        }
        reply.vdda_mv = analog_vdda_boot_mv;
        reply.tick_ms = HAL_GetTick();
        reply.supply_valid = reply.sample_rc == HAL_OK && analog_vdda_boot_valid &&
            reply.vdda_mv && reply.pc4_raw <= ADC_FULL_SCALE && reply.pc5_raw <= ADC_FULL_SCALE;
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
        reply.supply_valid &= reply.vdda_mv >= 3000U && reply.vdda_mv <= 3600U;
#endif
        reply.error_name = ZeroAdcOwner_DmaKind(request.kind) ?
            ZERO_ADC_DMA_PREFIX "_SUPPLY_UNVERIFIED" : "ZERO_SUPPLY_UNVERIFIED";
        if (!ZeroAdcOwner_Admitted(request.kind)) {
            reply.error_name = ZeroAdcOwner_DmaKind(request.kind) ?
                ZERO_ADC_DMA_PREFIX "_NOT_ADMITTED" : "ZERO_NOT_ADMITTED";
        } else if (reply.supply_valid) {
            uint32_t bus_mv = (uint32_t)(((uint64_t)reply.pc4_raw * reply.vdda_mv *
                ANALOG_VBUS_DIVIDER + ADC_FULL_SCALE / 2U) / ADC_FULL_SCALE);
            reply.bus_mv = bus_mv;
            uint8_t supply_matches = !(bus_mv < 10000U || bus_mv > 14000U);
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
            if (request.kind == ZERO_ADC_ACQUIRE_REFERENCE_OFF)
                supply_matches = bus_mv <= 1000U;
#endif
            if (!supply_matches) {
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
                reply.error_name = request.kind == ZERO_ADC_ACQUIRE_REFERENCE_OFF ?
                    "ADC3PAR_REFERENCE_REQUIRES_12V_OFF" : "ADC3PAR_REFERENCE_REQUIRES_12V_ON";
#else
                reply.error_name = ZeroAdcOwner_DmaKind(request.kind) ?
                    ZERO_ADC_DMA_PREFIX "_REQUIRES_12V_ANALOG_SUPPLY" :
                    "ZERO_REQUIRES_12V_ANALOG_SUPPLY";
#endif
            } else if (ZeroAdcOwner_DmaKind(request.kind)) {
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
                /* No second task can reconfigure ADC2 between this fresh
                 * voltage check and DMA ownership. Background is skipped
                 * until Service has stopped/restored every DMA writer. */
                if (AdcDmaDiag_Start(HAL_GetTick())) {
                    reply.error_name = NULL;
#if defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
                    zero_reference_power_kind = request.kind;
                    zero_reference_admit_mv = bus_mv;
#endif
                } else {
                    reply.error_name = ZERO_ADC_DMA_PREFIX "_ONESHOT_OR_CONFIG";
                }
#endif
            } else {
                uint16_t nominal = (uint16_t)((FOC_ZERO_NOMINAL_MV * ADC_FULL_SCALE +
                    reply.vdda_mv / 2U) / reply.vdda_mv);
                uint32_t mask = __get_PRIMASK();
                __disable_irq();
#if defined(ZERO_MEDIAN_DIAGNOSTIC)
                FocZeroMedian_Begin(&zero_median, &zero_retest_cal, nominal);
#if defined(FOC_ZERO_FAILURE_TRACE)
                FocTrace_Begin(&zero_trace);
#endif
#else
                FocZero_Begin(&zero_retest_cal, nominal);
#endif
                injected_seq_count = 0U;
                zero_retest_started_ms = HAL_GetTick();
                zero_retest_attempted = 1U;
                zero_retest_running = zero_retest_cal.state != FOC_ZERO_FAILED;
                if (zero_retest_running) TIM1->CR1 |= TIM_CR1_CEN;
                __set_PRIMASK(mask);
                reply.error_name = zero_retest_running ? NULL : "ZERO_CONFIG_FAILED";
            }
        }
    }
    /* One in-flight request; ProtocolTask is its only consumer. A mailbox
     * failure must stop the internal trigger rather than silently lose ACK. */
    if (xQueueSend(zero_adc_replies, &reply, 0U) != pdPASS) {
        zero_retest_interlock_fault = 1U;
        ZeroRetest_Stop();
        Error_Handler();
    }
}

static void ZeroRetest_SubmitAcquisition(uint32_t request_id, uint8_t kind)
{
    ZeroAdcRequest request = {request_id, kind};
    ZeroAdcReply reply;
    if (!zero_adc_requests || !zero_adc_replies ||
        xTaskGetCurrentTaskHandle() == zero_adc_owner_task ||
        xQueueSend(zero_adc_requests, &request, 0U) != pdPASS) {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "ZERO_ADC_OWNER_UNAVAILABLE");
        return;
    }
    /* The owner normally services the queue on its next <=10 ms loop; its HAL polls are
     * bounded at 2 ms each. Do not timeout/resend a possibly accepted request.
     * Blocking retains the local ProtocolTask routing context until reply. */
    if (xQueueReceive(zero_adc_replies, &reply, portMAX_DELAY) != pdPASS ||
        reply.request_id != request_id || reply.kind != kind) {
        Protocol_SendError(request_id, PROTO_ERR_NOT_READY, "ZERO_ADC_REPLY_MISMATCH");
        return;
    }
    if (reply.error_name) {
        char message[280];
        (void)Protocol_SendFormatted(message, sizeof(message),
            "%lu ERR %u %s ADC_OWNER=1 SUPPLY_ATTEMPT=%u SUPPLY_VALID=%u PC4_RAW=%u PC5_RAW=%u "
            "VDDA_MV=%u VBUS_EST_MV=%lu SAMPLE_RC=%u TICK_MS=%lu\r\n",
            (unsigned long)request_id, (unsigned)reply.error_code, reply.error_name,
            reply.supply_attempted, reply.supply_valid, reply.pc4_raw, reply.pc5_raw, reply.vdda_mv,
            (unsigned long)reply.bus_mv, reply.sample_rc, (unsigned long)reply.tick_ms);
    } else if (kind == ZERO_ADC_ACQUIRE_ZERO) {
        ZeroRetest_Format(request_id);
    }
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    else {
        ZeroRetest_DmaFormat(request_id);
    }
#endif
}
