/* Opt-in acceptance fixture, included by each APP after its declarations.
 * NOT a motor-control mode: SD, MOE and all output enables remain zero.
 * It runs the existing current-loop arithmetic with real ADC/encoder inputs.
 * Only the local console can request a fixed 60 s run. No routed command.
 */
static void FOC_ResetController(void);
#include "foc_current_zero.h"
static volatile uint8_t isolated_running;
static volatile uint8_t isolated_zero_ready, isolated_zero_shutdown_pending;
static FocZeroCal isolated_zero;
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
#if !defined(FOC_ISOLATED_CONCURRENCY)
#error Median acceptance is restricted to the hard-off compute-only fixture
#endif
#include "foc_zero_median.h"
#include "foc_current_median.h"
static FocZeroMedian isolated_zero_median;
#endif
static uint32_t isolated_zero_deadline;
static volatile uint32_t isolated_deadline;
static uint32_t isolated_start_adc, isolated_start_foc, isolated_start_ms;
static uint32_t isolated_end_ms, isolated_reason, isolated_runs;
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
static void ControlChain_Cancel(void);
static int ControlChain_DeadlineReached(uint32_t now_us);
#endif
static TaskHandle_t isolated_router_task, isolated_protocol_task;
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
static void FocFeedbackBinding_Disarm(void);
#endif

static void IsolatedZero_Fail(FocZeroReason reason)
{
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
    if (reason==FOC_ZERO_TIMEOUT) {
        DRIVER_SD_GPIO_Port->BSRR=(uint32_t)DRIVER_SD_Pin<<16U;
        TIM1->BDTR &= ~TIM_BDTR_MOE; TIM1->CCER=0U;
        FaultDiag_Capture(FOC_DIAG_STARTUP,7U,FOC_TO_STARTUP_ZERO,
            HAL_GetTick()-isolated_start_ms,FOC_ZERO_TIMEOUT_MS);
    }
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_EmergencyOff(FOC_FP_ZERO_INVALID);
#endif
    /* ISR-safe, immediate hard-off. DMA cleanup stays in the foreground. */
    if (isolated_zero.state == FOC_ZERO_FAILED && isolated_zero.reason != FOC_ZERO_OK)
        reason = isolated_zero.reason; /* Preserve the first failure evidence. */
    FocZero_Abort(&isolated_zero, reason);
    isolated_zero_ready = 0U;
    run_zero_cal_done = 0U;
    foc_enable = 0U;
    if (foc_fault == 0U) foc_fault_reason = FOC_FAULT_STARTUP_ZERO_CAL;
    foc_fault = 1U;
    TIM1->CR1 &= ~TIM_CR1_CEN;
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    isolated_end_ms = HAL_GetTick();
    isolated_running = 0U;
    isolated_zero_shutdown_pending = 1U;
}

static int IsolatedBench_Active(void)
{
    return isolated_running != 0U && isolated_zero_ready != 0U &&
           adc_fault == 0U && foc_fault == 0U &&
           (int32_t)(HAL_GetTick() - isolated_deadline) < 0;
}

static int IsolatedBench_Locked(void)
{
    return analog_safe_latched != 0U && foc_enable == 0U &&
           (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) == 0U &&
           (TIM1->BDTR & (TIM_BDTR_MOE | TIM_BDTR_AOE)) == 0U &&
           TIM1->CCER == 0U;
}

#if defined(FOC_FEEDBACK_SAFETY_BINDING)
#include "foc_feedback_binding_stm32.inc"
#endif

static void IsolatedBench_Stop(uint32_t reason)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
    ControlChain_Cancel();
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_Disarm();
#endif
    isolated_running = 0U;
    if (isolated_zero.state == FOC_ZERO_SETTLING ||
        isolated_zero.state == FOC_ZERO_COLLECTING) {
        FocZero_Abort(&isolated_zero, FOC_ZERO_STOPPED);
        isolated_zero_ready = run_zero_cal_done = 0U;
    }
    TIM1->CR1 &= ~TIM_CR1_CEN;
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    __DMB();
    __set_PRIMASK(mask);
    if (AS5047P_DmaIsPeriodic()) AS5047P_DmaStopPeriodic();
    isolated_zero_shutdown_pending = 0U;
    foc_enable = 0U;
    foc_id_ref_A = foc_iq_ref_A = 0.0f;
    analog_safe_latched = 1U;
    isolated_reason = reason;
    isolated_end_ms = HAL_GetTick();
}

static int IsolatedBench_Start(uint32_t duration_ms)
{
    if (duration_ms == 0U || duration_ms > 60000U || !IsolatedBench_Locked() ||
        adc_fault != 0U || foc_fault != 0U || encoder_valid == 0U ||
        fw_update.active != 0U || motor_control_mode != MOTOR_MODE_IDLE ||
        tightening_start_request != 0U || Tightening_IsBusy() != 0U)
        return 0;
    IsolatedBench_Stop(0U);
    FOC_ResetController();
    MotorControl_SetIdle();
    foc_id_ref_A = foc_iq_ref_A = 0.0f;
    encoder_theta_e_pred = encoder_theta_e;
    encoder_dma_cursor.valid = 0U;
    encoder_prev_valid = 0U;
    encoder_speed_dt_accum_s = 0.0f;
    /* INLINE here is a digital planner fixture only. The board's current
     * sense topology remains unconfirmed. No physical phase PWM is enabled.
     * OC4REF feeds TRGO2 internally with CCER=MOE=0. */
    if (FocAdcTiming_Commit(0.5f, 0.5f, 0.5f) != FOC_WINDOW_OK ||
        !FocAdcTiming_CanStart()) return 0;
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    isolated_zero_ready = run_zero_cal_done = current_filter_enable = 0U;
    uint16_t nominal = analog_vdda_boot_valid != 0U && analog_vdda_boot_mv != 0U ? (uint16_t)
        ((FOC_ZERO_NOMINAL_MV * ADC_FULL_SCALE + analog_vdda_boot_mv / 2U) /
         analog_vdda_boot_mv) : 0U;
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
    FocZeroMedian_Begin(&isolated_zero_median, &isolated_zero, nominal);
#else
    FocZero_Begin(&isolated_zero, nominal);
#endif
    if (isolated_zero.state == FOC_ZERO_FAILED) {
        __set_PRIMASK(mask);
        return 0;
    }
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    if (!FocFeedbackBinding_Arm(nominal)) {
        __set_PRIMASK(mask);
        return 0;
    }
#endif
    isolated_start_ms = HAL_GetTick();
    isolated_zero_deadline = isolated_start_ms + FOC_ZERO_TIMEOUT_MS;
    isolated_start_adc = injected_seq_count;
    isolated_start_foc = foc_control_count;
    isolated_end_ms = isolated_start_ms;
    isolated_deadline = isolated_start_ms + duration_ms;
    isolated_reason = 0U;
    ++isolated_runs;
    isolated_running = 1U;
    TIM1->DIER &= ~(TIM_DIER_UIE | TIM_DIER_CC4IE);
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    TIM1->CR1 |= TIM_CR1_CEN;
    __set_PRIMASK(mask);
    return 1;
}

static int IsolatedZero_Feed(uint16_t u, uint16_t v)
{
    if (isolated_zero_ready != 0U) return 0;
    if (isolated_running == 0U) return 1;
    if (!IsolatedBench_Locked()) {
        IsolatedZero_Fail(FOC_ZERO_UNSAFE);
        return 1;
    }
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
    /* A filtered READY permits arithmetic ONLY. The raw first-failure
     * evidence is retained and cannot authorize a physical power stage. */
    FocZeroMedian_Push(&isolated_zero_median, &isolated_zero, u, v);
#else
    FocZero_Push(&isolated_zero, u, v);
#endif
    if (isolated_zero.state == FOC_ZERO_FAILED) {
        IsolatedZero_Fail(isolated_zero.reason);
        return 1;
    }
    if (isolated_zero.state == FOC_ZERO_READY) {
        /* ADC ISR is the sole publisher; foreground snapshots mask this IRQ.
         * Keep this bounded: scalar stores only, no DMA/RTOS/logging calls. */
        iu_zero_raw = isolated_zero.zero_u;
        iv_zero_raw = isolated_zero.zero_v;
        iw_zero_raw = 2048U;
        iu_inj_raw = iu_zero_raw; iv_inj_raw = iv_zero_raw; iw_inj_raw = iw_zero_raw;
        current_valid_count = current_reject_count = current_reject_streak = 0U;
        current_last_rejected_sum_counts = 0;
        current_prev_raw_u = iu_zero_raw; current_prev_raw_v = iv_zero_raw;
        current_prev_raw_valid = 0U;
        current_med_u[0] = current_med_u[1] = current_med_u[2] = iu_zero_raw;
        current_med_v[0] = current_med_v[1] = current_med_v[2] = iv_zero_raw;
        current_med_index = current_med_count = 0U;
#if defined(FOC_CURRENT_SPIKE_ONLY)
        FocCurrentMedian_Begin(&current_spike_filter);
#endif
#if defined(FOC_CURRENT_TREND4)
        FocOcShadow_Begin(&foc_oc_shadow);
#if defined(FOC_FILTERED_OBSERVE_ONLY)
        FocOcShadow_Begin(&foc_filtered_oc_shadow);
#endif
        foc_trend_pairs=foc_trend_changed=foc_trend_u_changed=foc_trend_v_changed=0U;
#endif
        run_zero_valid_count = isolated_zero.count;
        run_zero_reject_count = isolated_zero.restarts;
        current_filter_enable = run_zero_cal_done = 1U;
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        FocFeedbackBinding_ZeroReady();
        if (foc_fault || adc_fault) return 1;
#endif
        __DMB();
        isolated_zero_ready = 1U;
    }
    return 1; /* The qualified last calibration pair is not a FOC command. */
}

static void IsolatedZero_Snapshot(FocZeroCal *out)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    FocZero_Snapshot(&isolated_zero, out);
    __set_PRIMASK(mask);
}

static void IsolatedZero_Format(char *out, size_t size)
{
    FocZeroCal c;
    IsolatedZero_Snapshot(&c);
    snprintf(out, size,
        "OK BENCH ZERO STATE=%u REASON=%u NOM=%u U0=%u V0=%u N=%lu SET=%lu "
        "RET=%lu S=%lu D=%lu RNG=%u:%u,%u:%u RAW=%u:%u,%u:%u LAST=%u,%u",
        (unsigned)c.state, (unsigned)c.reason, c.nominal, c.zero_u, c.zero_v,
        (unsigned long)c.count, (unsigned long)c.settled, (unsigned long)c.restarts,
        (unsigned long)c.span_restarts, (unsigned long)c.drift_restarts,
        c.min_u, c.max_u, c.min_v, c.max_v, c.observed_min_u, c.observed_max_u,
        c.observed_min_v, c.observed_max_v, c.last_u, c.last_v);
}

#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
static void IsolatedZero_FilterFormat(char *out, size_t size)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    FocZeroMedian m = isolated_zero_median;
    FocZeroState filtered = isolated_zero.state;
    __set_PRIMASK(mask);
    snprintf(out, size,
        "OK BENCH ZERO FILTER " FOC_CURRENT_FILTER_FIELDS "COMPUTE_ONLY=1 MOTOR_QUALIFIED=0 "
        "RAW_STATE=%u RAW_REASON=%u RAW_LAST=%u,%u RAW_RANGE=%u:%u,%u:%u "
        "OUT=%lu CHANGED=%lu PAIRS=%lu FILTER_STATE=%u RAW_WINDOW=%lu",
        (unsigned)m.raw.state, (unsigned)m.raw.reason, m.raw.last_u, m.raw.last_v,
        m.min_u, m.max_u, m.min_v, m.max_v, (unsigned long)m.outside_nominal,
        (unsigned long)m.changed, (unsigned long)m.pairs, (unsigned)filtered,
        (unsigned long)m.raw_window_pairs);
}
#endif

static void IsolatedZero_Wait(void)
{
    FocZeroCal result;
    char message[220];
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
    UART_SendLiteral("ISOLATED ZERO: " FOC_CURRENT_FILTER_NAME ", raw evidence retained; compute ONLY; SD=MOE=CCER=0\r\n");
#else
    UART_SendLiteral("ISOLATED ZERO: SD=MOE=CCER=0; actual 20kHz/12.5-cycle pairs; settling then 4000 stable raw pairs\r\n");
#endif
    for (;;) {
        IsolatedZero_Snapshot(&result);
        if (result.state == FOC_ZERO_READY || result.state == FOC_ZERO_FAILED) break;
        if (adc_fault != 0U || foc_fault != 0U || !IsolatedBench_Locked() ||
            (int32_t)(HAL_GetTick() - isolated_zero_deadline) >= 0) {
            uint32_t mask = __get_PRIMASK();
            __disable_irq();
            IsolatedZero_Fail(adc_fault != 0U || foc_fault != 0U ? FOC_ZERO_RATE :
                             !IsolatedBench_Locked() ? FOC_ZERO_UNSAFE : FOC_ZERO_TIMEOUT);
            __set_PRIMASK(mask);
        }
        vTaskDelay(pdMS_TO_TICKS(1U));
    }
    if (result.state != FOC_ZERO_READY) IsolatedBench_Stop(2U);
    snprintf(message, sizeof(message),
        "ISOLATED ZERO %s REASON=%u NOM=%u U0=%u V0=%u COUNT=%lu RESTARTS=%lu RANGE=%u..%u,%u..%u\r\n",
        result.state == FOC_ZERO_READY ? "PASS" : "FAIL", (unsigned)result.reason,
        result.nominal, result.zero_u, result.zero_v, (unsigned long)result.count,
        (unsigned long)result.restarts, result.min_u, result.max_u, result.min_v, result.max_v);
    UART_SendLiteral(message);
}

/* MotorControlTask remains the real 1 kHz encoder consumer/ACK owner. */
static void IsolatedBench_Service(void)
{
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    if (isolated_running && foc_feedback_armed && !FocFeedbackBinding_TimerHealthy())
        FocFeedbackBinding_EmergencyOff(FOC_FB_TIMER_INVALID);
#endif
    if (isolated_zero_shutdown_pending != 0U) IsolatedBench_Stop(2U);
    if (isolated_running == 0U) return;
    if ((isolated_zero_ready == 0U) &&
        (int32_t)(HAL_GetTick() - isolated_zero_deadline) >= 0) {
        uint32_t mask = __get_PRIMASK();
        __disable_irq();
        IsolatedZero_Fail(FOC_ZERO_TIMEOUT);
        __set_PRIMASK(mask);
        IsolatedBench_Stop(2U);
        return;
    }
    if ((int32_t)(HAL_GetTick() - isolated_deadline) >= 0 ||
        adc_fault != 0U || foc_fault != 0U || !IsolatedBench_Locked() ||
        (TIM1->CR1 & TIM_CR1_CEN) == 0U || fw_update.active != 0U)
    {
        IsolatedBench_Stop(adc_fault != 0U || foc_fault != 0U ? 2U :
                           !IsolatedBench_Locked() ? 3U : 1U);
        return;
    }
    if (!AS5047P_DmaIsPeriodic() && !AS5047P_DmaStartPeriodic())
        EncoderDma_FaultFromISR();
#if !defined(FOC_CONTROL_CHAIN_RECONNECT)
    if (foc_fault == 0U) (void)FOC_EncoderSpeedUpdate(0.001f);
#endif
    if (foc_fault != 0U || adc_fault != 0U) IsolatedBench_Stop(2U);
}

static void IsolatedBench_Format(char *out, size_t size)
{
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    uint32_t adc = injected_seq_count - isolated_start_adc;
    uint32_t foc = foc_control_count - isolated_start_foc;
    uint32_t elapsed = (isolated_running ? HAL_GetTick() : isolated_end_ms) - isolated_start_ms;
    uint8_t active = isolated_running;
    uint8_t zero = isolated_zero_ready;
    __set_PRIMASK(mask);
    snprintf(out, size,
             "OK BENCH ACTIVE=%u RUNS=%lu MS=%lu ADC=%lu FOC=%lu END=%lu LOCK=%u SD=%u MOE=%u CCER=%lu CEN=%u ZERO=%u",
             active, (unsigned long)isolated_runs, (unsigned long)elapsed,
             (unsigned long)adc, (unsigned long)foc, (unsigned long)isolated_reason,
             IsolatedBench_Locked(), (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) != 0U,
             (TIM1->BDTR & TIM_BDTR_MOE) != 0U, (unsigned long)TIM1->CCER,
             (TIM1->CR1 & TIM_CR1_CEN) != 0U, zero);
}

static void IsolatedBench_Stacks(char *out, size_t size)
{
    snprintf(out, size, "OK BENCH STACK MOTOR=%lu ROUTER=%lu PROTO=%lu TRANSFER=%lu HEAP=%lu MINHEAP=%lu",
             (unsigned long)(motor_control_task_handle ? uxTaskGetStackHighWaterMark(motor_control_task_handle) * sizeof(StackType_t) : 0U),
             (unsigned long)(isolated_router_task ? uxTaskGetStackHighWaterMark(isolated_router_task) * sizeof(StackType_t) : 0U),
             (unsigned long)(isolated_protocol_task ? uxTaskGetStackHighWaterMark(isolated_protocol_task) * sizeof(StackType_t) : 0U),
             (unsigned long)PW_RouterTransfer_StackFreeBytes(),
             (unsigned long)xPortGetFreeHeapSize(), (unsigned long)xPortGetMinimumEverFreeHeapSize());
}
