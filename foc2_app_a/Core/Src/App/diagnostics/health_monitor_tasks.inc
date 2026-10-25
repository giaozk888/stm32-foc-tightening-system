/* App A diagnostics/health_monitor_tasks.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static void BootHealthTask(void *argument)
{
    TickType_t last_wake_time;
    uint32_t last_adc_count;
    uint32_t last_foc_count;

    (void)argument;

    boot_health_trial_active = 0U;
    boot_health_last_sample_ok = 0U;
    boot_health_stable_ms = 0U;
    boot_health_elapsed_ms = 0U;
    g_boot_health_fail_mask = 0U;
    g_boot_health_last_adc_delta = 0U;
    g_boot_health_last_foc_delta = 0U;
    g_boot_health_sample_count = 0U;

    /*
     * StartupTask creates this task only after ADC/FOC, UART RX/TX and the
     * main application tasks have all been initialized. Give the just-created
     * peer tasks one scheduling interval before examining the trial state.
     */
    vTaskDelay(pdMS_TO_TICKS(BOOT_HEALTH_CHECK_MS));

    if (BootHealth_IsCurrentTrial() == 0U)
    {
        UART_SendLiteral(
            "BOOT HEALTH: current slot is already confirmed; auto-confirm task idle\r\n");
        vTaskDelete(NULL);
        return;
    }

    boot_health_trial_active = 1U;

    UART_SendLiteral(
        "BOOT HEALTH: TRIAL slot detected -> require 5s continuous healthy window\r\n"
        "BOOT HEALTH: START/FW BEGIN/BOOT switch locked until confirmation\r\n");

    last_wake_time = xTaskGetTickCount();
    last_adc_count = injected_seq_count;
    last_foc_count = foc_control_count;

    for (;;)
    {
        uint32_t adc_now;
        uint32_t foc_now;
        uint32_t adc_delta;
        uint32_t foc_delta;
        uint32_t fail_mask;
        uint8_t sample_ok;
        BootMetaV2_t meta;

        vTaskDelayUntil(
            &last_wake_time,
            pdMS_TO_TICKS(BOOT_HEALTH_CHECK_MS));

        /*
         * Manual FW CONFIRM is still supported. If another task already
         * confirmed this APP, there is nothing left for auto-confirm to do.
         */
        if ((BootMeta_ReadV3(&meta) != 0U) &&
            (meta.pending_slot != APP_THIS_SLOT))
        {
            boot_health_trial_active = 0U;
            boot_health_last_sample_ok = 1U;
            UART_SendLiteral(
                "BOOT HEALTH: trial state cleared externally -> task complete\r\n");
            vTaskDelete(NULL);
            return;
        }

        adc_now = injected_seq_count;
        foc_now = foc_control_count;

        adc_delta = adc_now - last_adc_count;
        foc_delta = foc_now - last_foc_count;

        last_adc_count = adc_now;
        last_foc_count = foc_now;

        boot_health_elapsed_ms += BOOT_HEALTH_CHECK_MS;
        g_boot_health_last_adc_delta = adc_delta;
        g_boot_health_last_foc_delta = foc_delta;
        g_boot_health_sample_count++;

        fail_mask = 0U;

        if (BOOT_HEALTH_FORCE_FAIL_TEST != 0U)
        {
            fail_mask |= BOOT_HEALTH_FAIL_FORCED;
        }

        if (adc_fault != 0U)
        {
            fail_mask |= BOOT_HEALTH_FAIL_ADC_FAULT;
        }

        if (foc_fault != 0U)
        {
            fail_mask |= BOOT_HEALTH_FAIL_FOC_FAULT;
        }

        if (encoder_valid == 0U)
        {
            fail_mask |= BOOT_HEALTH_FAIL_ENCODER;
        }

#if defined(FOC_ISOLATED_CONCURRENCY)
        if (!IsolatedBench_Active() || !IsolatedBench_Locked())
#else
        if (foc_enable == 0U)
#endif
        {
            fail_mask |= BOOT_HEALTH_FAIL_FOC_DISABLED;
        }

        if (UART_Async_IsReady() == 0U)
        {
            fail_mask |= BOOT_HEALTH_FAIL_UART;
        }

        /*
         * In 500 ms a healthy 20 kHz chain should produce about 10,000
         * injected/current-loop executions. 9,000 leaves reasonable margin
         * while still detecting a badly stalled real-time chain.
         */
        if (adc_delta < BOOT_HEALTH_MIN_ADC_DELTA)
        {
            fail_mask |= BOOT_HEALTH_FAIL_ADC_RATE;
        }

        if (foc_delta < BOOT_HEALTH_MIN_FOC_DELTA)
        {
            fail_mask |= BOOT_HEALTH_FAIL_FOC_RATE;
        }

        /*
         * Trial firmware is intentionally kept in a non-working service state
         * until confirmation. This protects the known-good opposite slot from
         * being overwritten and prevents a tightening cycle during trial.
         */
        if (fw_update.active != 0U)
        {
            fail_mask |= BOOT_HEALTH_FAIL_FW_ACTIVE;
        }

        if ((Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U))
        {
            fail_mask |= BOOT_HEALTH_FAIL_TIGHTENING;
        }

        if (motor_control_mode != MOTOR_MODE_IDLE)
        {
            fail_mask |= BOOT_HEALTH_FAIL_MOTOR_MODE;
        }

        if (fabsf(encoder_speed_rpm) > 2.0f)
        {
            fail_mask |= BOOT_HEALTH_FAIL_SPEED;
        }

        g_boot_health_fail_mask = fail_mask;
        sample_ok = (fail_mask == 0U) ? 1U : 0U;
        boot_health_last_sample_ok = sample_ok;

        if (sample_ok != 0U)
        {
            boot_health_stable_ms += BOOT_HEALTH_CHECK_MS;
        }
        else
        {
            boot_health_stable_ms = 0U;
        }

        if (boot_health_stable_ms >=
            BOOT_HEALTH_STABLE_REQUIRED_MS)
        {
            /*
             * Enter a quiet hardware state before handing confirmation to the
             * bootloader. The APP itself no longer erases/programs Metadata V3.
             */
            UART_SendLiteral(
                "BOOT HEALTH: PASS 5s -> requesting bootloader confirmation\r\n");

            Fw_EnterSafeState();
            vTaskDelay(pdMS_TO_TICKS(20U));

            if (BootMeta_ConfirmCurrent() != 0U)
            {
                char msg[128];

                UART_SendFormatted(
                    msg,
                    sizeof(msg),
                    "BOOT HEALTH: CONFIRM REQUESTED SLOT=%c -> RESETTING\r\n",
                    (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B');

                boot_health_trial_active = 0U;
                vTaskDelay(pdMS_TO_TICKS(150U));
                NVIC_SystemReset();
            }
            else
            {
                UART_SendLiteral(
                    "BOOT HEALTH: SRAM mailbox confirm request FAILED -> RESET for retry/rollback\r\n");
                vTaskDelay(pdMS_TO_TICKS(150U));
                NVIC_SystemReset();
            }
        }

        /*
         * A trial that never establishes a healthy window must not remain
         * running forever. Reset without confirming; Bootloader V3 consumes
         * the next attempt and eventually returns to confirmed_slot.
         */
        if (boot_health_elapsed_ms >=
            BOOT_HEALTH_FAIL_RESET_MS)
        {
            UART_SendLiteral(
                "BOOT HEALTH: FAIL timeout -> NOT CONFIRMED -> RESET for rollback\r\n");

            Fw_EnterSafeState();
            vTaskDelay(pdMS_TO_TICKS(150U));
            NVIC_SystemReset();
        }
    }
}


#if defined(FOC_FAST_CURRENT_REJECT)
/* Task-only formatting: reserve Flash for the O2 realtime chain. */
__attribute__((optimize("Os")))
#endif
static void MonitorTask(void *argument)
{
    TickType_t last_sample_tick;
    TickType_t analog_wake_tick;
    TickType_t last_stack_tick;
#if defined(FOC_FAST_CURRENT_REJECT)
    TickType_t last_current_stats_tick=0U;
#endif
    uint32_t last_adc_count;
    uint32_t last_foc_count;

    (void)argument;

    last_sample_tick = xTaskGetTickCount();
    analog_wake_tick = last_sample_tick;
    last_stack_tick = last_sample_tick;
    last_adc_count = injected_seq_count;
    last_foc_count = foc_control_count;

#if defined(CAN_STATUS_TELEMETRY)
    /* A failed CAN interface does not change the motor-control path. */
    (void)CAN_StatusTx_Init();
#endif

    for (;;)
    {
        uint32_t adc_now;
        uint32_t foc_now;
        uint32_t adc_delta;
        uint32_t foc_delta;
        uint32_t adc_rate_hz;
        uint32_t foc_rate_hz;
        uint32_t monitor_period_ms;
        uint32_t sample_elapsed_ms;
        TickType_t now_tick;
        MotorControlMode_t mode;
        TighteningTestStage_t test_stage;
        uint32_t test_ms;
        uint32_t contact_ms;
        uint8_t contact_cond;
        uint32_t cycle_no;
        uint32_t uart_tx_queued;
        uint32_t uart_tx_dropped;
        uint32_t uart_dma_errors;
        uint32_t uart_rx_queued;
        uint32_t uart_rx_dropped;
        uint32_t fault_reason;
        uint8_t foc_en;
        uint8_t foc_flt;

        float pos;
        float ptgt;
        float perr;
        float spd;
        float spd_raw;
        float spd_det;
        float vcmd;
        float sref;
        float iqref;
        float id;
        float iq;
        float speed_cmd;
        float iq_cmd;
        float travel_deg;
        float post_contact_travel_deg;
        float drive_iqref_A;

        int32_t pos_x100;
        int32_t ptgt_x100;
        int32_t perr_x100;
        int32_t spd_x10;
        int32_t spd_raw_x10;
        int32_t spd_det_x10;
        int32_t vcmd_x10;
        int32_t sref_x10;
        int32_t speed_cmd_x10;
        int32_t iq_cmd_mA;
        int32_t iqref_mA;
        int32_t drive_iqref_mA;
        int32_t travel_x10;
        int32_t post_travel_x10;
        int32_t id_mA;
        int32_t iq_mA;

        char pos_buf[20];
        char ptgt_buf[20];
        char perr_buf[20];
        char msg[768];

        /*
         * Wake at 10 Hz for IDLE-only analog diagnostics. Keep the existing
         * human-readable UART monitor rate at 3 s IDLE / 1 s active.
         * This low-priority task never calls HAL_ADC_Stop() on ADC2.
         */
        monitor_period_ms =
            (Tightening_IsBusy() != 0U) ? 1000U : 3000U;

        vTaskDelayUntil(&analog_wake_tick,
                        pdMS_TO_TICKS(ANALOG_LIVE_PERIOD_MS));

        FaultDiag_Monitor(); /* Task-only, immutable first-fault evidence. */
#if defined(FOC_DQ_AUDIT_ENABLE)
        DqAudit_Monitor();
#endif
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
        SpeedAccelFf_Monitor(); /* Decimated token logs, not the control owner. */
#endif

#if defined(CAN_STATUS_TELEMETRY)
        CAN_StatusTx_Service(HAL_GetTick());
        {
            uint8_t flags = 0U;
            if (foc_enable != 0U) flags |= CAN_STATUS_FLAG_FOC_ENABLED;
            if (foc_fault != 0U) flags |= CAN_STATUS_FLAG_FAULT_LATCHED;
            if (encoder_valid != 0U) flags |= CAN_STATUS_FLAG_ENCODER_VALID;
            if (HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) == GPIO_PIN_SET)
                flags |= CAN_STATUS_FLAG_DRIVER_SD_HIGH;
            CAN_StatusTx_Publish((uint8_t)motor_control_mode, flags,
                                 (uint16_t)foc_fault_reason);
        }
#endif

        if ((motor_control_mode == MOTOR_MODE_IDLE) &&
            (Tightening_IsBusy() == 0U))
        {
            (void)ADC_AnalogLiveSample();
        }
        else
        {
            analog_live_valid = 0U;
        }

#if defined(CAN_STATUS_TELEMETRY)
        {
            uint32_t vbus_mv = 0U;
            uint8_t vbus_ok = 0U;
            if ((analog_live_valid != 0U) &&
                (analog_vdda_boot_valid != 0U) &&
                (analog_live_sample_count != 0U) &&
                ((HAL_GetTick() - analog_live_last_tick_ms) <= ANALOG_LIVE_FRESH_MS))
            {
                vbus_mv = (uint32_t)
                    (((uint64_t)analog_live_pc4_raw *
                      (uint64_t)analog_vdda_boot_mv *
                      ANALOG_VBUS_DIVIDER + (ADC_FULL_SCALE / 2U)) /
                     ADC_FULL_SCALE);
                vbus_ok = 1U;
            }
            CAN_StatusTx_PublishMotor(encoder_position_deg, foc_iq_A,
                                      encoder_valid,
                                      (foc_enable != 0U) && (foc_fault == 0U) &&
                                      (encoder_valid != 0U) &&
                                      (analog_safe_latched == 0U));
            CAN_StatusTx_PublishElectrical(vbus_mv, encoder_speed_rpm,
                                           vbus_ok, encoder_valid);
        }
#endif

#if defined(CAN_LOG_STREAM) || defined(CAN_RPC_READ_ONLY)
        /* Give the three telemetry frames time to leave the hardware FIFO.
           MonitorTask remains the only FDCAN owner; producers never wait. */
        vTaskDelay(pdMS_TO_TICKS(5U));
#if defined(CAN_RPC_READ_ONLY)
        PW_CanRpc_MonitorService(HAL_GetTick());
#endif
#if defined(CAN_LOG_STREAM)
        PW_CanLog_Service(HAL_GetTick());
#endif
#endif

#if defined(ESP_NETWORK_OBSERVER)
        {
            static uint32_t last_network_ms;
            uint32_t network_ms = HAL_GetTick();
            if ((uint32_t)(network_ms - last_network_ms) >= 1000U) {
                last_network_ms = network_ms;
                NetworkObserver_Publish(NET_KIND_SAMPLE);
            }
        }
#endif
        now_tick = xTaskGetTickCount();

        /* Scan MotorCtrl stack only from this lower-priority task. */
        if ((motor_control_task_handle != NULL) &&
            ((now_tick - last_stack_tick) >= pdMS_TO_TICKS(1000U)))
        {
            uint32_t free_words = (uint32_t)
                uxTaskGetStackHighWaterMark(motor_control_task_handle);
            if (free_words < motor_stack_min_words)
            {
                motor_stack_min_words = free_words;
            }
            motor_stack_samples++;
            last_stack_tick = now_tick;
        }

        if ((now_tick - last_sample_tick) <
            pdMS_TO_TICKS(monitor_period_ms))
        {
            continue;
        }

        sample_elapsed_ms =
            (uint32_t)((now_tick - last_sample_tick) *
                       portTICK_PERIOD_MS);

        if (sample_elapsed_ms == 0U)
        {
            sample_elapsed_ms = monitor_period_ms;
        }

        adc_now = injected_seq_count;
        foc_now = foc_control_count;

        adc_delta = adc_now - last_adc_count;
        foc_delta = foc_now - last_foc_count;

        adc_rate_hz =
            (uint32_t)(((uint64_t)adc_delta * 1000ULL) /
                       (uint64_t)sample_elapsed_ms);

        foc_rate_hz =
            (uint32_t)(((uint64_t)foc_delta * 1000ULL) /
                       (uint64_t)sample_elapsed_ms);

        last_sample_tick = now_tick;
#if defined(FOC_FAST_CURRENT_REJECT)
        if ((TickType_t)(now_tick-last_current_stats_tick)>=pdMS_TO_TICKS(5000U)) {
            last_current_stats_tick=now_tick;
            ProtectedLoop_CurrentMonitor();
        }
#endif
        last_adc_count = adc_now;
        last_foc_count = foc_now;

        mode = motor_control_mode;
        test_stage = tightening_test_stage;
        test_ms = tightening_test_elapsed_ms;
        contact_ms = tightening_contact_candidate_ms;
        contact_cond = tightening_contact_condition;
        cycle_no = tightening_cycle_number;

        uart_tx_queued =
            (uint32_t)UART_Async_GetQueuedBytes();
        uart_tx_dropped =
            UART_Async_GetDroppedBytes();
        uart_dma_errors =
            UART_Async_GetDmaErrorCount();
        uart_rx_queued =
            (uint32_t)UART_RxDma_GetQueuedBytes();
        uart_rx_dropped =
            UART_RxDma_GetDroppedBytes();

        fault_reason = foc_fault_reason;
        foc_en = foc_enable;
        foc_flt = foc_fault;

        pos = encoder_position_deg;
        ptgt = position_target_deg;
        perr = position_error_deg;
        spd = encoder_speed_rpm;
        spd_raw = encoder_rpm_instant;
        spd_det = encoder_speed_detect_rpm;
        vcmd = speed_target_rpm;
        sref = speed_ref_rpm;
        speed_cmd = motor_speed_command_rpm;
        iq_cmd = motor_iq_command_A;
        travel_deg = tightening_travel_deg;
        post_contact_travel_deg =
            tightening_post_contact_travel_deg;
        drive_iqref_A = tightening_drive_iqref_A;
        iqref = foc_iq_ref_A;
        id = foc_id_A;
        iq = foc_iq_A;

        pos_x100 = (int32_t)(pos * 100.0f);
        ptgt_x100 = (int32_t)(ptgt * 100.0f);
        perr_x100 = (int32_t)(perr * 100.0f);

        spd_x10 = (int32_t)(spd * 10.0f);
        spd_raw_x10 = (int32_t)(spd_raw * 10.0f);
        spd_det_x10 = (int32_t)(spd_det * 10.0f);
        vcmd_x10 = (int32_t)(vcmd * 10.0f);
        sref_x10 = (int32_t)(sref * 10.0f);
        speed_cmd_x10 = (int32_t)(speed_cmd * 10.0f);

        iq_cmd_mA = (int32_t)(iq_cmd * 1000.0f);
        iqref_mA = (int32_t)(iqref * 1000.0f);
        drive_iqref_mA = (int32_t)(drive_iqref_A * 1000.0f);
        travel_x10 = (int32_t)(travel_deg * 10.0f);
        post_travel_x10 =
            (int32_t)(post_contact_travel_deg * 10.0f);
        id_mA = (int32_t)(id * 1000.0f);
        iq_mA = (int32_t)(iq * 1000.0f);

        FormatSignedX100(pos_buf, sizeof(pos_buf), pos_x100);
        FormatSignedX100(ptgt_buf, sizeof(ptgt_buf), ptgt_x100);
        FormatSignedX100(perr_buf, sizeof(perr_buf), perr_x100);

        UART_SendFormatted(
            msg,
            sizeof(msg),
            "RTOS-FOC CYCLE=%lu/%u MODE=%s TST=%u t=%lums | "
            "ADC/s=%lu FOC/s=%lu EN=%u FLT=%u R=%lu | "
            "POS=%s PTGT=%s PERR=%s deg | "
            "CTRL=%ld.%01ld DET=%ld.%01ld RAW=%ld.%01ld | "
            "CMD=%ld.%01ld VCMD=%ld.%01ld REF=%ld.%01ld rpm | "
            "IqCmd=%ldmA IqRef=%ldmA DriveIq=%ldmA | "
            "TRV=%ld.%01lddeg PTRV=%ld.%01lddeg C=%u CT=%lums | "
            "Id=%ldmA Iq=%ldmA | PDB=%u AHLD=%u G=%lu | "
            "UTXQ=%lu UDROP=%lu UERR=%lu RXQ=%lu RXDROP=%lu\r\n",
            (unsigned long)cycle_no,
            (unsigned int)TIGHTEN_REPEAT_CYCLES,
            MotorControl_ModeName(mode),
            (unsigned int)test_stage,
            (unsigned long)test_ms,
            (unsigned long)adc_rate_hz,
            (unsigned long)foc_rate_hz,
            (unsigned int)foc_en,
            (unsigned int)foc_flt,
            (unsigned long)fault_reason,
            pos_buf,
            ptgt_buf,
            perr_buf,
            (long)(spd_x10 / 10),
            (long)labs(spd_x10 % 10),
            (long)(spd_det_x10 / 10),
            (long)labs(spd_det_x10 % 10),
            (long)(spd_raw_x10 / 10),
            (long)labs(spd_raw_x10 % 10),
            (long)(speed_cmd_x10 / 10),
            (long)labs(speed_cmd_x10 % 10),
            (long)(vcmd_x10 / 10),
            (long)labs(vcmd_x10 % 10),
            (long)(sref_x10 / 10),
            (long)labs(sref_x10 % 10),
            (long)iq_cmd_mA,
            (long)iqref_mA,
            (long)drive_iqref_mA,
            (long)(travel_x10 / 10),
            (long)labs(travel_x10 % 10),
            (long)(post_travel_x10 / 10),
            (long)labs(post_travel_x10 % 10),
            (unsigned int)contact_cond,
            (unsigned long)contact_ms,
            (long)id_mA,
            (long)iq_mA,
            (unsigned int)position_deadband_active,
            (unsigned int)active_hold_enable,
            (unsigned long)encoder_speed_glitch_count,
            (unsigned long)uart_tx_queued,
            (unsigned long)uart_tx_dropped,
            (unsigned long)uart_dma_errors,
            (unsigned long)uart_rx_queued,
            (unsigned long)uart_rx_dropped);
#if defined(CAN_STATUS_TELEMETRY)
        {
            CAN_StatusTx_Health can_health;
            CAN_StatusTx_GetHealth(&can_health);
            UART_SendFormatted(msg, sizeof(msg),
                     "CAN HEALTH READY=%u HALT=%u INIT=%lu FAIL=%lu RECOVER=%lu "
                     "BO=%lu FIFO_STALL=%lu ENQ=%lu DONE=%lu EVT_LOST=%lu "
                     "FULL=%lu ADD_FAIL=%lu "
                     "TEC=%lu REC=%lu LEC=%lu FREE=%lu\r\n",
                     (unsigned int)can_health.ready,
                     (unsigned int)can_health.recovery_exhausted,
                     (unsigned long)can_health.init_attempts,
                     (unsigned long)can_health.init_failures,
                     (unsigned long)can_health.recoveries,
                     (unsigned long)can_health.bus_off_events,
                     (unsigned long)can_health.fifo_stalls,
                     (unsigned long)can_health.tx_enqueued,
                     (unsigned long)can_health.tx_completed,
                     (unsigned long)can_health.tx_event_lost,
                     (unsigned long)can_health.tx_fifo_full,
                     (unsigned long)can_health.tx_add_failures,
                     (unsigned long)can_health.tx_error_count,
                     (unsigned long)can_health.rx_error_count,
                     (unsigned long)can_health.last_error_code,
                     (unsigned long)can_health.fifo_free);
        }
#if defined(CAN_SHADOW_DIAG)
        {
            CAN_ShadowHealth shadow;
            CAN_StatusTx_GetShadowHealth(&shadow);
            UART_SendFormatted(msg, sizeof(msg),
                     "CAN SHADOW RX=%lu BAD=%lu REPLY=%lu DROP=%lu "
                     "TIMEOUT=%lu STOP_TEST=%lu RANGE=%lu OVERRUN=%lu "
                     "NO_MOTOR_ACTION=1\r\n",
                     (unsigned long)shadow.received,
                     (unsigned long)shadow.invalid_frames,
                     (unsigned long)shadow.replies_queued,
                     (unsigned long)shadow.replies_dropped,
                     (unsigned long)shadow.probe_timeouts,
                     (unsigned long)shadow.stop_tests,
                     (unsigned long)shadow.range_rejects,
                     (unsigned long)shadow.fifo_overruns);
        }
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
        {
            CAN_ControlRejectHealth control;
            CAN_StatusTx_GetControlRejectHealth(&control);
            UART_SendFormatted(msg, sizeof(msg),
                     "CAN CONTROL RX=%lu BAD=%lu REJECT=%lu REPLY=%lu "
                     "DROP=%lu OVERRUN=%lu EXEC_DISABLED=1\r\n",
                     (unsigned long)control.received,
                     (unsigned long)control.invalid_frames,
                     (unsigned long)control.rejected,
                     (unsigned long)control.replies_queued,
                     (unsigned long)control.replies_dropped,
                     (unsigned long)control.fifo_overruns);
        }
#endif
#endif
    }
}


