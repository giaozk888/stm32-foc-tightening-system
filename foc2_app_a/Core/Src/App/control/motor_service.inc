/* App A control/motor_service.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static void MotorControl_SetIdle(void)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_IDLE) ProtectedLoop_PwmInvalidate();
#endif
    motor_position_command_deg = encoder_position_deg;
    motor_speed_command_rpm = 0.0f;
    motor_iq_command_A = 0.0f;
    motor_position_active_hold = 0U;

    /*
     * Publish mode last.  At worst the 1 kHz reader sees the previous mode
     * for one additional cycle; it will never see a new mode with stale
     * command data.
     */
    motor_control_mode = MOTOR_MODE_IDLE;
}


static void MotorControl_SetSpeed(float rpm)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_SPEED) ProtectedLoop_PwmInvalidate();
#endif
    rpm = ClampFloat(rpm,
                     -MOTOR_SPEED_API_LIMIT_RPM,
                      MOTOR_SPEED_API_LIMIT_RPM);

    motor_speed_command_rpm = rpm;
    motor_iq_command_A = 0.0f;
    motor_position_active_hold = 0U;
    motor_control_mode = MOTOR_MODE_SPEED;
}


static void MotorControl_SetPosition(float position_deg, uint8_t active_hold)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_POSITION) ProtectedLoop_PwmInvalidate();
#endif
    motor_position_command_deg = position_deg;
    motor_speed_command_rpm = 0.0f;
    motor_iq_command_A = 0.0f;
    motor_position_active_hold = (active_hold != 0U) ? 1U : 0U;
    motor_control_mode = MOTOR_MODE_POSITION;
}


static void MotorControl_SetIq(float iq_A)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (motor_control_mode!=MOTOR_MODE_IQ) ProtectedLoop_PwmInvalidate();
#endif
    iq_A = ClampFloat(iq_A,
                      -MOTOR_DIRECT_IQ_LIMIT_A,
                       MOTOR_DIRECT_IQ_LIMIT_A);

    motor_iq_command_A = iq_A;
    motor_speed_command_rpm = 0.0f;
    motor_position_active_hold = 0U;
    motor_control_mode = MOTOR_MODE_IQ;
}


static const char *MotorControl_ModeName(MotorControlMode_t mode)
{
    switch (mode)
    {
        case MOTOR_MODE_POSITION: return "POS";
        case MOTOR_MODE_SPEED:    return "SPD";
        case MOTOR_MODE_IQ:       return "IQ";
        case MOTOR_MODE_IDLE:
        default:                  return "IDLE";
    }
}


/*
 * High-priority deterministic 1 kHz motor-control task.
 *
 * This task no longer owns the old 0 -> +90 -> 0 -> -90 -> 0 demo state
 * machine.  It is now a reusable motor-control service.  The application layer
 * selects POSITION / SPEED / IQ / IDLE through the generic command mailbox.
 *
 * The 20 kHz current loop remains entirely inside the ADC injected ISR.
 */
#if defined(FOC_ISOLATED_CONCURRENCY)
#include "isolated_concurrency.inc"
#endif
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
#include "control_chain_reconnect.inc"
#endif
#if defined(FOC_PROTECTED_CLOSED_LOOP)
#include "protected_closed_loop.inc"
#if defined(FOC_BEMF_CANDIDATE)
#include "foc_bemf_feedforward_binding.inc"
#endif
#if defined(FOC_DQ_DECOUPLING_CANDIDATE)
#include "foc_dq_decoupling_binding.inc"
#endif
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
#include "speed_accel_feedforward_binding.inc"
#endif
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
#include "speed_friction_compensation_binding.inc"
#endif
#if defined(FOC_LATEST_ORIGINAL_FSM)
#include "latest_original_fsm.inc"
#endif
#endif
static void MotorControlTask(void *argument)
{
    TickType_t last_wake_time;
    uint32_t last_adc_count;
    uint32_t last_foc_count;

    (void)argument;

    last_wake_time = xTaskGetTickCount();

    UART_SendLiteral(
        "MotorControlTask started @ 1kHz\r\n"
        "Generic modes: IDLE / POSITION / SPEED / IQ\r\n"
        "20kHz current loop remains in ADC injected ISR\r\n");

    last_adc_count = injected_seq_count;
    last_foc_count = foc_control_count;
    preflight_adc_progress_tick = xTaskGetTickCount();
    preflight_foc_progress_tick = preflight_adc_progress_tick;

    for (;;)
    {
        TickType_t now = xTaskGetTickCount();
        uint32_t adc_now = injected_seq_count;
        uint32_t foc_now = foc_control_count;

#if defined(FOC_PROTECTED_CLOSED_LOOP)
        ProtectedLoop_TaskService();
        if (adc_now != last_adc_count) { last_adc_count=adc_now; preflight_adc_progress_tick=now; }
        if (foc_now != last_foc_count) { last_foc_count=foc_now; preflight_foc_progress_tick=now; }
        vTaskDelayUntil(&last_wake_time,pdMS_TO_TICKS(1U));
        continue;
#endif

#if defined(FOC_ISOLATED_CONCURRENCY)
        IsolatedBench_Service();
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
        /* Reuse the original outer-loop task, but NEVER unlock power gates. */
        if (!IsolatedBench_Active())
        {
            MotorControl_SetIdle();
            foc_iq_ref_A = 0.0f;
            vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
            continue;
        }
#else
        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
        continue;
#endif
#endif
        /* Stopping TIM1 for analog diagnostics intentionally stops the
         * injected ADC/FOC counters; it is not an ADC-chain fault. */
#if !defined(FOC_CONTROL_CHAIN_RECONNECT)
        if (analog_safe_latched != 0U)
        {
#if defined(AS5047P_SPI_DMA)
            if (AS5047P_DmaIsPeriodic()) AS5047P_DmaStopPeriodic();
#endif
            foc_enable = 0U;
            foc_iq_ref_A = 0.0f;
            PowerStage_Disable();
            __HAL_TIM_MOE_DISABLE(&htim1);
            vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
            continue;
        }
#endif

        if (adc_now != last_adc_count)
        {
            last_adc_count = adc_now;
            preflight_adc_progress_tick = now;
        }
        if (foc_now != last_foc_count)
        {
            last_foc_count = foc_now;
            preflight_foc_progress_tick = now;
        }
        /*
         * A stalled 20 kHz ADC/FOC chain must disable the bridge even after
         * START has already passed preflight.  Only arm this check after run
         * zero calibration; otherwise the intentional startup gap would
         * falsely latch a fault.  Keep the first fault reason intact.
         */
        if ((run_zero_cal_done != 0U) &&
            (adc_fault == 0U) && (foc_fault == 0U))
        {
            if ((now - preflight_adc_progress_tick) >
                pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
            {
                foc_fault_reason = FOC_FAULT_ADC_CHAIN_STALE;
                foc_fault = 1U;
                PowerStage_Disable();
                FaultDiag_Capture(FOC_DIAG_MOTOR,FOC_FAULT_ADC_CHAIN_STALE,
                    FOC_TO_ADC_CHAIN,(uint32_t)((now-preflight_adc_progress_tick)*portTICK_PERIOD_MS),
                    PREFLIGHT_CHAIN_MAX_STALE_MS);
            }
            else if ((now - preflight_foc_progress_tick) >
                     pdMS_TO_TICKS(PREFLIGHT_CHAIN_MAX_STALE_MS))
            {
                foc_fault_reason = FOC_FAULT_CONTROL_CHAIN_STALE;
                foc_fault = 1U;
                PowerStage_Disable();
                FaultDiag_Capture(FOC_DIAG_MOTOR,FOC_FAULT_CONTROL_CHAIN_STALE,
                    FOC_TO_CONTROL_CHAIN,(uint32_t)((now-preflight_foc_progress_tick)*portTICK_PERIOD_MS),
                    PREFLIGHT_CHAIN_MAX_STALE_MS);
            }
        }
        if ((adc_fault == 0U) && (foc_fault == 0U))
        {
#if defined(AS5047P_SPI_DMA)
            if (!AS5047P_DmaIsPeriodic())
            {
                encoder_dma_cursor.valid = 0U;
                encoder_prev_valid = 0U;
                encoder_speed_dt_accum_s = 0.0f;
                if (!AS5047P_DmaStartPeriodic()) EncoderDma_FaultFromISR();
            }
            if (foc_fault == 0U)
            {
                HAL_StatusTypeDef update = FOC_EncoderSpeedUpdate(0.001f);
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
                if (update == HAL_OK && control_chain_active)
                    ++control_chain_outer_steps;
#else
                (void)update;
#endif
            }
#else
            (void)FOC_EncoderSpeedUpdate(0.001f);
#endif
        }

        /*
         * Immediate safe-state reaction.  The lower-priority application task
         * cannot override a latched hardware/control fault.
         */
        if ((adc_fault != 0U) || (foc_fault != 0U))
        {
#if defined(AS5047P_SPI_DMA)
            if (AS5047P_DmaIsPeriodic()) AS5047P_DmaStopPeriodic();
#endif
            foc_enable = 0U;
            foc_iq_ref_A = 0.0f;

            motor_speed_command_rpm = 0.0f;
            motor_iq_command_A = 0.0f;
            speed_target_rpm = 0.0f;
            speed_ref_rpm = 0.0f;
            speed_integrator_A = 0.0f;
            stall_timer_s = 0.0f;

            motor_control_mode = MOTOR_MODE_IDLE;

            PowerStage_Disable();
            PWM_SetDuty(0.5f, 0.5f, 0.5f);
        }

        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(1U));
    }
}


