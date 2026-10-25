/* App A application/tightening_task.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
#if defined(FOC_PSI_IDENT_DIAG)
#include "psi_ke_identification_binding.inc"
#elif defined(FOC_CURRENT_STEP_AB_DIAG)
#include "current_step_ab_binding.inc"
#elif defined(FOC_MOTOR_IDENTIFICATION_DIAG)
#include "motor_identification_binding.inc"
#elif defined(FOC_FRICTION_CALIBRATION_DIAG)
#include "friction_calibration_binding.inc"
#elif defined(FOC_INTENT_FSM_CANDIDATE)
#include "tightening_intent_binding.inc"
#else
#include "tightening_rundown_binding.inc"
/* Size-optimize only the 100Hz application FSM, not any FOC/PI/IRQ function. */
__attribute__((optimize("Os")))
static void TighteningTask(void *argument)
{
    TickType_t last_wake_time;
    TickType_t stage_start;
    uint32_t stop_confirm_ms = 0U;

    (void)argument;

    last_wake_time = xTaskGetTickCount();
    stage_start = last_wake_time;

    memset(tightening_cycle_summary,
           0,
           sizeof(tightening_cycle_summary));

    tightening_cycle_number = 1U;
    tightening_cycle_ok_count = 0U;
    tightening_start_request = 0U;
    tightening_stop_request = 0U;
    tightening_result_request = 0U;
    tightening_start_request_id = 0U;
    tightening_stop_request_id = 0U;
    tightening_result_request_id = 0U;
    tightening_cycle_request_id = 0U;
    tightening_last_outcome = TIGHTEN_OUTCOME_NONE;

    /*
     * Enum value 0 is kept for compatibility, but now means WAIT_COMMAND.
     * There is no automatic 2-second startup rundown.
     */
    tightening_test_stage = TIGHTEN_STATE_IDLE_DELAY;
    TighteningRepeat_ResetCurrentCycle();

    MotorControl_SetIdle();

    UART_SendLiteral(
        "\r\n"
        "TighteningTask started\r\n"
        "COMMAND-DRIVEN SINGLE-CYCLE MODE\r\n"
        "Device remains IDLE until UART command START\r\n"
        "\r\n"
        "State flow after START:\r\n"
        "  WAIT_COMMAND\r\n"
        "  -> RUNDOWN (runtime rpm)\r\n"
        "  -> CONTACT (runtime thresholds)\r\n"
        "  -> IDLE / wait until stopped\r\n"
        "  -> SEATING      (runtime current/time)\r\n"
        "  -> TIGHTEN #1   (runtime current/time)\r\n"
        "  -> TIGHTEN #2   (runtime current/time)\r\n"
        "  -> TIGHTEN #3   (runtime current/time)\r\n"
        "  -> HOLD         (runtime current/time)\r\n"
        "  -> COMPLETE / IDLE\r\n"
        "\r\n"
        "STOP is accepted at any time\r\n"
        "RESULT reprints the latest terminal result\r\n"
        "Important: Iq is NOT calibrated torque/N.m\r\n"
        "Post-contact abort: runtime speed/travel limits\r\n"
        "RUNDOWN abort: runtime timeout/travel limits\r\n"
        "Result recorder: 100Hz per-stage statistics\r\n"
        "PARAMS: use <REQ_ID> GET PARAMS / SET <PARAM> <VALUE>\r\n"
        "\r\n");

    for (;;)
    {
        TickType_t now = xTaskGetTickCount();
#if defined(FOC_TORQUE_CHAIN_DIAG)
        TorqueChain_Service();
#endif
#if defined(FOC_SPEED_DYNAMIC_DIAG) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND) || defined(FOC_ANGLE_CHAIN_DIAG)
        /* Separate single-mode experiment. Never enter fixed-Iq tightening
         * stages or consume normal START into the original FSM here. */
        ProtectedLoop_RundownEnd();
        vTaskDelay(pdMS_TO_TICKS(10U));
        continue;
#endif
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
        ControlChain_TaskService();
#endif
        uint32_t elapsed_ms =
            (uint32_t)((now - stage_start) * portTICK_PERIOD_MS);

        float det_rpm = encoder_speed_detect_rpm;
        float drive_iqref =
            TIGHTEN_DIRECTION * foc_iq_ref_A;
        float travel =
            fabsf(encoder_position_deg - tightening_start_position_deg);
        float post_contact_travel =
            fabsf(encoder_position_deg - tightening_contact_position_deg);

        tightening_test_elapsed_ms = elapsed_ms;
        tightening_drive_iqref_A = drive_iqref;
        tightening_travel_deg = travel;
        tightening_post_contact_travel_deg = post_contact_travel;

        /*
         * STOP is consumed by the application owner. The lower-level motor
         * service still owns the actual transition to IDLE.
         */
        if (tightening_stop_request != 0U)
        {
            uint8_t was_busy = Tightening_IsBusy();
            uint32_t stop_request_id = tightening_stop_request_id;
            char proto_msg[160];

            tightening_stop_request = 0U;
            tightening_stop_request_id = 0U;
            MotorControl_SetIdle();

            tightening_contact_candidate_ms = 0U;
            tightening_contact_condition = 0U;
            tightening_drive_iqref_A = 0.0f;
            stop_confirm_ms = 0U;

            if (was_busy != 0U)
            {
                tightening_last_outcome = TIGHTEN_OUTCOME_STOPPED;
                tightening_test_stage = TIGHTEN_STATE_DONE;
                stage_start = now;
                tightening_test_elapsed_ms = 0U;

                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu STOPPED START_REQ=%lu\r\n",
                    (unsigned long)stop_request_id,
                    (unsigned long)tightening_cycle_request_id);

                Protocol_SendCycleEvent("COMPLETE", "STOPPED");

                UART_SendLiteral(
                    "TIGHTEN: STOP command -> IDLE\r\n");

                if (tightening_result_printed == 0U)
                {
                    tightening_result_printed = 1U;
                    TighteningResult_PrintSummary("STOPPED");
                }
            }
            else
            {
                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu ALREADY_IDLE\r\n",
                    (unsigned long)stop_request_id);

                UART_SendLiteral(
                    "TIGHTEN: STOP command -> already IDLE\r\n");
            }
        }

        if (tightening_start_request != 0U)
        {
            uint32_t start_request_id;
            uint8_t start_request_routed;
            uint16_t start_request_source_node;
            char proto_msg[160];

            /*
             * The producer publishes tightening_start_request last.  After
             * observing it, acquire the associated correlation/route fields.
             */
            __DMB();
            start_request_id = tightening_start_request_id;
            start_request_routed = tightening_start_request_routed;
            start_request_source_node =
                tightening_start_request_source_node;

            tightening_start_request = 0U;
            tightening_start_request_id = 0U;
            tightening_start_request_routed = 0U;
            tightening_start_request_source_node = 0U;

            if ((adc_fault != 0U) || (foc_fault != 0U))
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "FAULT");
            }
            else if (Tightening_IsBusy() != 0U)
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "BUSY");
            }
            else if (fabsf(encoder_speed_rpm) >
                     TIGHTEN_REPEAT_RESTART_MAX_RPM)
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "ROTOR_MOVING");
            }
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
            else if (!ControlChain_StartReady(start_request_id) &&
                     SystemPreflight_FailMask() != 0U)
#else
            else if (SystemPreflight_FailMask() != 0U)
#endif
            {
                Protocol_SendDeferredStartError(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id,
                    "PREFLIGHT_NOT_READY");
            }
#if defined(FOC_LATEST_ORIGINAL_FSM)
            else if (start_request_routed || !LatestOriginal_Admit())
            {
                Protocol_SendDeferredStartError(
                    start_request_routed, start_request_source_node,
                    start_request_id, "LATEST_BACKEND_NOT_READY");
            }
#endif
            else
            {
                memset(tightening_cycle_summary,
                       0,
                       sizeof(tightening_cycle_summary));

                tightening_cycle_number = 1U;
                tightening_cycle_ok_count = 0U;
                tightening_last_outcome = TIGHTEN_OUTCOME_NONE;
                tightening_cycle_request_id = start_request_id;

                /*
                 * Stage 4.1: this is the point where the START has really
                 * become a tightening cycle, so make its origin persistent.
                 */
                TighteningSession_Begin(
                    start_request_routed,
                    start_request_source_node,
                    start_request_id);

                TighteningRepeat_ResetCurrentCycle();

                tightening_start_position_deg =
                    encoder_position_deg;
                tightening_travel_deg = 0.0f;
                stop_confirm_ms = 0U;

                MotorControl_SetSpeed(
                    TIGHTEN_DIRECTION *
                    (float)recipe_state.params.rundown_rpm);

                tightening_test_stage =
                    TIGHTEN_STATE_RUNDOWN;
                stage_start = now;
                tightening_test_elapsed_ms = 0U;
                tightening_travel_deg = 0.0f;
                tightening_post_contact_travel_deg = 0.0f;

                snprintf(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT REQ=%lu STARTED MODE=RUNDOWN TARGET=%lurpm",
                    (unsigned long)tightening_cycle_request_id,
                    (unsigned long)recipe_state.params.rundown_rpm);
                if (Protocol_AsyncEventEnqueue(
                        g_tightening_session_routed,
                        g_tightening_session_owner_node,
                        proto_msg) == 0U)
                {
                    UART_SendLiteral("EVT ASYNC QUEUE FULL: STARTED LOST\r\n");
                }

                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "EVT SESSION ACTIVE=1 ROUTED=%u OWNER=%u START_REQ=%lu\r\n",
                    (unsigned int)g_tightening_session_routed,
                    (unsigned int)g_tightening_session_owner_node,
                    (unsigned long)g_tightening_session_request_id);

                UART_SendLiteral(
                    "TIGHTEN: START -> RUNDOWN\r\n");

                /*
                 * IMPORTANT:
                 * elapsed_ms / travel / post_contact_travel were calculated
                 * at the top of this loop while we were still in WAIT_COMMAND.
                 * If the board had been idle for >8 s, using those stale
                 * values in the RUNDOWN switch below would immediately trigger
                 * RUNDOWN_TIMEOUT in the very same 10 ms iteration, before
                 * MotorControlTask could act on MOTOR_MODE_SPEED.
                 *
                 * End this application iteration here.  The next 100 Hz tick
                 * recomputes all state-derived values from the new RUNDOWN
                 * baseline.
                 */
                vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(10U));
                continue;
            }
        }

        if (tightening_result_request != 0U)
        {
            uint32_t result_request_id =
                tightening_result_request_id;
            char proto_msg[192];

            tightening_result_request = 0U;
            tightening_result_request_id = 0U;

            if (Tightening_IsBusy() != 0U)
            {
                Protocol_SendError(
                    result_request_id,
                    PROTO_ERR_BUSY,
                    "BUSY");
            }
            else if (tightening_last_outcome ==
                     TIGHTEN_OUTCOME_NONE)
            {
                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu OK RESULT NONE START_REQ=0\r\n",
                    (unsigned long)result_request_id);
            }
            else
            {
                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu OK RESULT DATA START_REQ=%lu OUTCOME=%s CONTACT=%u\r\n",
                    (unsigned long)result_request_id,
                    (unsigned long)tightening_cycle_request_id,
                    TighteningOutcome_Name(tightening_last_outcome),
                    (unsigned int)tightening_contact_confirmed);

                TighteningResult_PrintSummary(
                    TighteningOutcome_Name(
                        tightening_last_outcome));

                UART_SendFormatted(
                    proto_msg,
                    sizeof(proto_msg),
                    "%lu END RESULT\r\n",
                    (unsigned long)result_request_id);
            }
        }

        /*
         * Latched lower-level faults always win.
         * There is no automatic restart from FAULT.
         */
        if ((adc_fault != 0U) || (foc_fault != 0U))
        {
            if (tightening_test_stage != TIGHTEN_STATE_FAULT)
            {
                MotorControl_SetIdle();

                tightening_test_stage = TIGHTEN_STATE_FAULT;
                tightening_last_outcome = TIGHTEN_OUTCOME_FAULT;
                tightening_contact_candidate_ms = 0U;
                tightening_contact_condition = 0U;
                tightening_drive_iqref_A = 0.0f;

                Protocol_SendCycleEvent("COMPLETE", "FAULT");

                UART_SendLiteral(
                    "TIGHTEN: FAULT -> IDLE, no automatic restart\r\n");
            }

            vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(10U));
            continue;
        }

        switch (tightening_test_stage)
        {
            case TIGHTEN_STATE_IDLE_DELAY:
                /* WAIT_COMMAND: START handling above is the only entry path. */
                tightening_contact_candidate_ms = 0U;
                tightening_contact_condition = 0U;
                tightening_drive_iqref_A = 0.0f;
                tightening_post_contact_travel_deg = 0.0f;
                break;

            case TIGHTEN_STATE_RUNDOWN:
            {
                uint8_t contact_now = 0U;
                if (TightenRundown_Update(&tightening_rundown,elapsed_ms,
                    TIGHTEN_DIRECTION*(float)recipe_state.params.rundown_rpm,
                    encoder_speed_rpm,det_rpm,encoder_position_deg,
                    foc_iq_ref_A,encoder_valid)) {
                    Tightening_NoRotation(elapsed_ms);
                    break;
                }

                /*
                 * A contact candidate must satisfy BOTH:
                 *   1) low 50 ms average mechanical speed
                 *   2) substantial q-axis current demand
                 *
                 * and remain true continuously for 250 ms.
                 */
                if (TightenRundown_CanContact(&tightening_rundown) &&
                    (fabsf(det_rpm) <=
                     (float)recipe_state.params.contact_rpm) &&
                    (drive_iqref >=
                     ((float)recipe_state.params.contact_iq_mA / 1000.0f)))
                {
                    contact_now = 1U;
                }

                tightening_contact_condition = contact_now;

                if (contact_now != 0U)
                {
                    if (tightening_contact_candidate_ms <
                        recipe_state.params.contact_ms)
                    {
                        tightening_contact_candidate_ms += 10U;
                    }
                }
                else
                {
                    tightening_contact_candidate_ms = 0U;
                }

                if (TightenRundown_CanContact(&tightening_rundown) &&
                    tightening_contact_candidate_ms >=
                    recipe_state.params.contact_ms)
                {
                    /*
                     * Latch contact position BEFORE removing the speed command.
                     * All later torque-mode travel is measured from here.
                     */
                    tightening_contact_position_deg =
                        encoder_position_deg;
                    tightening_post_contact_travel_deg = 0.0f;
                    tightening_contact_confirmed = 1U;

                    MotorControl_SetIdle();

                    tightening_test_stage =
                        TIGHTEN_STATE_CONTACT_STOP;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;
                    stop_confirm_ms = 0U;

                    /*
                     * Clear candidate/log values on the state transition so
                     * the monitor does not keep showing CT=250 ms forever.
                     */
                    tightening_contact_candidate_ms = 0U;
                    tightening_contact_condition = 0U;
                    tightening_drive_iqref_A = 0.0f;

                    UART_SendLiteral(
                        "TIGHTEN: CONTACT CONFIRMED -> IDLE stop\r\n");
                }
                else if ((elapsed_ms >=
                          recipe_state.params.rundown_timeout_ms) ||
                         (travel >=
                          (float)recipe_state.params.max_travel_deg))
                {
                    PowerStage_Disable();
                    FaultDiag_Capture(FOC_DIAG_PROCESS,TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT,
                        elapsed_ms>=recipe_state.params.rundown_timeout_ms ? FOC_TO_RUNDOWN : FOC_TO_NONE,
                        elapsed_ms,recipe_state.params.rundown_timeout_ms);
                    MotorControl_SetIdle();

                    tightening_test_stage =
                        TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;
                    tightening_contact_candidate_ms = 0U;
                    tightening_contact_condition = 0U;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "RUNDOWN_TIMEOUT");

                    UART_SendLiteral(
                        "TIGHTEN: RUNDOWN timeout/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary(
                            "RUNDOWN_TIMEOUT");
                    }
                }
                break;
            }

            case TIGHTEN_STATE_CONTACT_STOP:
                tightening_contact_condition = 0U;
                tightening_contact_candidate_ms = 0U;

                if (fabsf(encoder_speed_rpm) <=
                    TIGHTEN_STOP_MAX_RPM)
                {
                    if (stop_confirm_ms <
                        TIGHTEN_STOP_CONFIRM_MS)
                    {
                        stop_confirm_ms += 10U;
                    }
                }
                else
                {
                    stop_confirm_ms = 0U;
                }

                if (stop_confirm_ms >=
                    TIGHTEN_STOP_CONFIRM_MS)
                {
                    TighteningResult_Reset(
                        &tighten_result_seating,
                        ((float)recipe_state.params.seating_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.seating_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_SEATING_IQ;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;

                    UART_SendLiteral(
                        "TIGHTEN: SEATING started\r\n");
                }
                else if (elapsed_ms >=
                         TIGHTEN_STOP_TIMEOUT_MS)
                {
                    PowerStage_Disable();
                    FaultDiag_Capture(FOC_DIAG_PROCESS,TIGHTEN_OUTCOME_STOP_TIMEOUT,
                        FOC_TO_STOP_SETTLE,elapsed_ms,TIGHTEN_STOP_TIMEOUT_MS);
                    MotorControl_SetIdle();

                    tightening_test_stage =
                        TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_STOP_TIMEOUT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "STOP_TIMEOUT");

                    UART_SendLiteral(
                        "TIGHTEN: stop timeout -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("STOP_TIMEOUT");
                    }
                }
                break;

            case TIGHTEN_STATE_SEATING_IQ:
                TighteningResult_Sample(&tighten_result_seating);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.seating_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_010,
                        ((float)recipe_state.params.t1_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.t1_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_010;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: TIGHTEN #1\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_010:
                TighteningResult_Sample(&tighten_result_010);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.t1_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_012,
                        ((float)recipe_state.params.t2_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.t2_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_012;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: TIGHTEN #2\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_012:
                TighteningResult_Sample(&tighten_result_012);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.t2_ms)
                {
                    TighteningResult_Reset(
                        &tighten_result_015,
                        ((float)recipe_state.params.t3_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.t3_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_TIGHTEN_015;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: TIGHTEN #3\r\n");
                }
                break;

            case TIGHTEN_STATE_TIGHTEN_015:
                TighteningResult_Sample(&tighten_result_015);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendLiteral(
                        "TIGHTEN: torque-stage speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.t3_ms)
                {
                    /*
                     * HOLD keeps the same +0.15 A command; only the state/time
                     * changes so the log clearly separates final hold.
                     */
                    TighteningResult_Reset(
                        &tighten_result_hold,
                        ((float)recipe_state.params.hold_iq_mA / 1000.0f));

                    MotorControl_SetIq(
                        TIGHTEN_DIRECTION *
                        ((float)recipe_state.params.hold_iq_mA / 1000.0f));

                    tightening_test_stage =
                        TIGHTEN_STATE_HOLD;
                    stage_start = now;

                    UART_SendLiteral(
                        "TIGHTEN: HOLD started\r\n");
                }
                break;

            case TIGHTEN_STATE_HOLD:
                TighteningResult_Sample(&tighten_result_hold);

                if ((fabsf(encoder_speed_rpm) >=
                     (float)recipe_state.params.torque_abort_rpm) ||
                    (post_contact_travel >=
                     (float)recipe_state.params.post_travel_max_deg))
                {
                    MotorControl_SetIdle();
                    tightening_test_stage = TIGHTEN_STATE_TIMEOUT;
                    stage_start = now;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_ABORT;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "ABORT");

                    UART_SendLiteral(
                        "TIGHTEN: HOLD speed/travel abort -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("ABORT");
                    }
                }
                else if (elapsed_ms >=
                         recipe_state.params.hold_ms)
                {
                    if (!TightenRundown_CanOk(&tightening_rundown,
                                             tightening_contact_confirmed)) {
                        Tightening_NoRotation(elapsed_ms);
                        break;
                    }
                    MotorControl_SetIdle();

                    stage_start = now;
                    tightening_test_elapsed_ms = 0U;
                    tightening_contact_candidate_ms = 0U;
                    tightening_contact_condition = 0U;
                    tightening_drive_iqref_A = 0.0f;

                    tightening_last_outcome =
                        TIGHTEN_OUTCOME_OK;
                    tightening_test_stage =
                        TIGHTEN_STATE_DONE;

                    Protocol_SendCycleEvent(
                        "COMPLETE",
                        "OK");

                    UART_SendLiteral(
                        "TIGHTEN: COMPLETE -> IDLE\r\n");

                    if (tightening_result_printed == 0U)
                    {
                        tightening_result_printed = 1U;
                        TighteningResult_PrintSummary("OK");
                        TighteningRepeat_StoreCurrentCycle();
                    }

                    UART_SendLiteral(
                        "TIGHTEN: cycle finished; send START for another cycle\r\n");
                }
                break;

            case TIGHTEN_STATE_CYCLE_PAUSE:
                /* Legacy enum; Layer 1B does not auto-restart. */
                MotorControl_SetIdle();
                tightening_test_stage = TIGHTEN_STATE_DONE;
                break;

            case TIGHTEN_STATE_DONE:
            case TIGHTEN_STATE_TIMEOUT:
            case TIGHTEN_STATE_FAULT:
            default:
                /*
                 * IDLE already published on entry.
                 * Do not continuously re-latch PTGT and do not auto-restart.
                 */
                tightening_contact_condition = 0U;
                tightening_contact_candidate_ms = 0U;
                break;
        }

#if defined(FOC_LATEST_ORIGINAL_FSM)
        /* Record the terminal RUNDOWN frame before session STOP can freeze
         * the startup trace. No ISR instrumentation added. */
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
        ProtectedLoop_RundownEnd();
#endif
        LatestOriginal_FsmService();
#endif
        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(10U));
    }
}


#endif /* legacy task excluded only from the opt-in intent candidate */
