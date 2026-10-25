/* Original control tasks, not a second motor/plant model. This opt-in build
 * permits arithmetic commands ONLY: all physical output gates remain hard off.
 * ProtocolTask publishes a single bounded request; TighteningTask owns mode
 * changes and the existing START mailbox. No automatic run/retry/fault clear.
 */
#if !defined(FOC_CONTROL_CHAIN_RECONNECT) || FOC_CONTROL_CHAIN_RECONNECT != 1 || \
    !defined(FOC_FEEDBACK_SAFETY_BINDING) || FOC_FEEDBACK_SAFETY_BINDING != 1 || \
    !defined(FOC_ISOLATED_CONCURRENCY) || FOC_ISOLATED_CONCURRENCY != 1
#error Control chain reconnect requires the hard-off feedback binding
#endif

enum { CONTROL_CHAIN_SPEED = 1U, CONTROL_CHAIN_IQ = 2U,
       CONTROL_CHAIN_TIGHTEN = 3U, CONTROL_CHAIN_DURATION_MS = 5000U };
static volatile uint8_t control_chain_request, control_chain_active;
static volatile uint8_t control_chain_used, control_chain_stop;
static uint8_t control_chain_kind, control_chain_start_pending;
static uint32_t control_chain_request_id, control_chain_start_id;
static uint32_t control_chain_deadline, control_chain_start_ms;
static uint32_t control_chain_start_us;
static uint32_t control_chain_outer_steps, control_chain_app_steps;
static uint32_t control_chain_start_foc, control_chain_end_foc, control_chain_end_ms;

/* TIM7 checks this on its independent 1 MHz clock as well as the task's
 * millisecond deadline. A delayed application task cannot extend the lease. */
static int ControlChain_DeadlineReached(uint32_t now_us)
{
    return control_chain_active &&
        (uint32_t)(now_us - control_chain_start_us) >= CONTROL_CHAIN_DURATION_MS * 1000U;
}

/* Callers serialize this predicate and publication with PRIMASK. FOC enable
 * is deliberately NEVER set: SystemPreflight/normal START stay motor-locked. */
static int ControlChain_Ready(void)
{
    TickType_t now = xTaskGetTickCount();
    return IsolatedBench_Active() && IsolatedBench_Locked() &&
        encoder_valid && !adc_fault && !foc_fault && run_zero_cal_done &&
        !fw_update.active && !BootHealth_IsCurrentTrial() && UART_Async_IsReady() &&
        foc_feedback_armed && foc_feedback_zero_ready &&
        FocFeedbackBinding_TimerHealthy() && foc_feedback_work_n != 0U &&
        (uint32_t)(AS5047P_DmaNowUs() - foc_feedback_last_us) <= 100U &&
        foc_feedback_safety.protection.result == FOC_OC_CLEAR &&
        (now - preflight_adc_progress_tick) <= pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS) &&
        (now - preflight_foc_progress_tick) <= pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS);
}

/* Stop/fault/deadline invalidates pending requests, never resets guardian or
 * PI state into a new run. TighteningTask consumes its ordinary STOP mailbox. */
static void ControlChain_Cancel(void)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    if (control_chain_active || control_chain_request) {
        tightening_stop_request_id = control_chain_request_id;
        tightening_stop_request = 1U;
    }
    control_chain_request = control_chain_active = control_chain_stop = 0U;
    control_chain_start_pending = 0U;
    tightening_start_request = 0U;
    foc_iq_ref_A = 0.0f;
    MotorControl_SetIdle();
    control_chain_end_foc = foc_control_count;
    control_chain_end_ms = HAL_GetTick();
    __DMB(); __set_PRIMASK(mask);
}

/* Recheck only the diagnostic request, not normal START or RPC admission. */
static int ControlChain_StartReady(uint32_t request_id)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    int ready = control_chain_start_pending && control_chain_active &&
        control_chain_kind == CONTROL_CHAIN_TIGHTEN &&
        request_id == control_chain_start_id && ControlChain_Ready() &&
        (int32_t)(HAL_GetTick() - control_chain_deadline) < 0 &&
        motor_control_mode == MOTOR_MODE_IDLE && !Tightening_IsBusy() &&
        fabsf(encoder_speed_rpm) <= TIGHTEN_REPEAT_RESTART_MAX_RPM;
    /* One consumption, including rejection. No later normal request inherits
     * this diagnostic permission by reusing a correlation ID. */
    control_chain_start_pending = 0U;
    __set_PRIMASK(mask); return ready;
}

/* This is called at the beginning of the REAL 100 Hz TighteningTask. */
static void ControlChain_TaskService(void)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    if (control_chain_stop || (control_chain_active &&
        (!IsolatedBench_Active() || !IsolatedBench_Locked() || adc_fault || foc_fault ||
         fw_update.active || BootHealth_IsCurrentTrial() ||
         (int32_t)(HAL_GetTick() - control_chain_deadline) >= 0))) {
        ControlChain_Cancel();
        __set_PRIMASK(mask); return;
    }
    uint8_t request = control_chain_request;
    control_chain_request = 0U;
    if (request) {
        if (!ControlChain_Ready() || Tightening_IsBusy() || tightening_start_request ||
            motor_control_mode != MOTOR_MODE_IDLE ||
            fabsf(encoder_speed_rpm) > TIGHTEN_REPEAT_RESTART_MAX_RPM) {
            ControlChain_Cancel();
            __set_PRIMASK(mask); return;
        }
        control_chain_active = 1U; control_chain_kind = request;
        control_chain_start_ms = HAL_GetTick();
        control_chain_start_us = AS5047P_DmaNowUs();
        control_chain_deadline = control_chain_start_ms + CONTROL_CHAIN_DURATION_MS;
        control_chain_start_foc = foc_control_count;
        control_chain_outer_steps = control_chain_app_steps = 0U;
        if (request == CONTROL_CHAIN_SPEED) MotorControl_SetSpeed(20.0f);
        else if (request == CONTROL_CHAIN_IQ) MotorControl_SetIq(0.10f);
        else {
            control_chain_start_pending = 1U;
            control_chain_start_id = control_chain_request_id;
            tightening_start_request_id = control_chain_request_id;
            tightening_start_request_routed = 0U;
            tightening_start_request_source_node = 0U;
            __DMB(); tightening_start_request = 1U;
        }
    }
    if (control_chain_active) ++control_chain_app_steps;
    __set_PRIMASK(mask);
}

/* Local-only admission is enforced by Protocol_HandleLine before this call.
 * Fixed commands, no variable setpoint, no saved recipe or expanded limits. */
static void ControlChain_Command(const char *cmd, uint32_t request_id,
                                 char *out, size_t size)
{
    if (strcmp(cmd, "BENCH CHAIN STATUS") == 0) {
        uint32_t mask = __get_PRIMASK(); __disable_irq();
        uint32_t elapsed = (control_chain_active ? HAL_GetTick() : control_chain_end_ms) - control_chain_start_ms;
        uint32_t current_steps = (control_chain_active ? foc_control_count : control_chain_end_foc) - control_chain_start_foc;
        uint32_t outer = control_chain_outer_steps, app = control_chain_app_steps;
        uint8_t active = control_chain_active, pending = control_chain_request, used = control_chain_used, kind = control_chain_kind;
        __set_PRIMASK(mask);
        snprintf(out, size, "OK BENCH CHAIN HARD_OFF=1 MOTOR_QUALIFIED=0 ACTIVE=%u PENDING=%u USED=%u KIND=%u MS=%lu OUTER=%lu APP=%lu CURRENT=%lu", active, pending, used, kind,
            (unsigned long)elapsed, (unsigned long)outer, (unsigned long)app, (unsigned long)current_steps);
        return;
    }
    if (strcmp(cmd, "BENCH CHAIN STOP") == 0) {
        uint32_t mask = __get_PRIMASK(); __disable_irq();
        control_chain_stop = 1U;
        /* Reference clears now; state-machine STOP is owned by its task. */
        foc_iq_ref_A = 0.0f;
        __set_PRIMASK(mask);
        snprintf(out, size, "OK BENCH CHAIN STOP QUEUED=1 HARD_OFF=1");
        return;
    }
    uint8_t request = strcmp(cmd, "BENCH CHAIN SPEED") == 0 ? CONTROL_CHAIN_SPEED :
        strcmp(cmd, "BENCH CHAIN IQ") == 0 ? CONTROL_CHAIN_IQ :
        strcmp(cmd, "BENCH CHAIN TIGHTEN") == 0 ? CONTROL_CHAIN_TIGHTEN : 0U;
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    int accepted = request && !control_chain_used && !control_chain_active &&
        !control_chain_request && !control_chain_stop && ControlChain_Ready() &&
        motor_control_mode == MOTOR_MODE_IDLE && !Tightening_IsBusy() &&
        !tightening_start_request && fabsf(encoder_speed_rpm) <= TIGHTEN_REPEAT_RESTART_MAX_RPM;
    if (accepted) {
        control_chain_used = 1U; control_chain_request_id = request_id;
        __DMB(); control_chain_request = request;
    }
    __set_PRIMASK(mask);
    snprintf(out, size, accepted ? "OK BENCH CHAIN QUEUED=1 HARD_OFF=1 MAX_MS=5000 MOTOR_QUALIFIED=0" :
        "ERR 109 CONTROL_CHAIN_REJECTED HARD_OFF=1");
}
