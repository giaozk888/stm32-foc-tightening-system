/* App A startup/startup_task.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/* USER CODE END 0 */

#if defined(CAN_STATUS_TELEMETRY)
/* Keep the bridge off while reporting an unpowered/invalid current-sense
 * zero over CAN. No motor or command task is started on this path. */
static void StartupZeroCalFaultCommsLoop(void)
{
    PowerStage_Disable();
    PWM_StopAll();
    foc_enable = 0U;
    foc_fault = 1U;
    foc_fault_reason = FOC_FAULT_STARTUP_ZERO_CAL;
    FaultDiag_Capture(FOC_DIAG_STARTUP,FOC_FAULT_STARTUP_ZERO_CAL,FOC_TO_NONE,
        tightening_test_elapsed_ms,0U);
    adc_fault = 1U;
    motor_control_mode = MOTOR_MODE_IDLE;

    (void)CAN_StatusTx_Init();
    for (;;)
    {
        PowerStage_Disable();
        FaultDiag_Monitor(); /* No MonitorTask is created on this failure path. */
        CAN_StatusTx_Service(HAL_GetTick());
        CAN_StatusTx_Publish(MOTOR_MODE_IDLE,
                             CAN_STATUS_FLAG_FAULT_LATCHED,
                             FOC_FAULT_STARTUP_ZERO_CAL);
        CAN_StatusTx_PublishMotor(0.0f, 0.0f, 0U, 0U);
        CAN_StatusTx_PublishElectrical(0U, 0.0f, 0U, 0U);
        vTaskDelay(pdMS_TO_TICKS(100U));
    }
}
#endif


#if defined(ZERO_RETEST_BOOT)
#include "zero_retest_boot.inc"
#endif
#if defined(SAFETY_LOCKED_BOOT)
#include "safety_locked_boot.inc"
#endif

#if defined(FOC_BREAKAWAY_FIVE_SECOND)
/* Diagnostic Flash budget only; never change FOC/PI/IRQ code generation. */
__attribute__((optimize("Os")))
#endif
static void StartupTask(void *argument)
{
    uint32_t seq_start;
    uint32_t seq_delta;
    char msg[160];

    (void)argument;

    /*
     * Scheduler is running from this point onward, so HAL_Delay() and
     * FreeRTOS timing can safely coexist through the shared SysTick handler.
     */
    g_rtos_started = 1U;
    g_uart_async_runtime_enable = 0U;
#if defined(ZERO_RETEST_BOOT)
    ZeroRetest_RunForever();
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    analog_safe_latched = 1U;
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    PowerStage_Disable();
#endif
#if defined(SAFETY_LOCKED_BOOT)
    /* Before KVS migration, encoder checks, PWM, calibration or command tasks. */
    SafetyLockedBoot_RunForever();
#endif

    /*
     * IMPORTANT:
     * Keep UART blocking during StartupTask bring-up.
     *
     * StartupTask runs at priority 5 and its existing HAL_Delay() calls are
     * busy-wait based.  If the low-priority DMA TX service task is created
     * here, it cannot run while StartupTask remains runnable, so all startup
     * messages appear to disappear after "Starting scheduler...".
     *
     * We therefore switch to async TX only after all bring-up/calibration
     * work is complete.
     */
    PowerStage_Disable();
    foc_enable = 0U;
    foc_fault = 0U;
    foc_fault_reason = 0U;
    FaultDiag_Clear();
    adc_fault = 0U;

    if (g_safe_comm_boot != 0U)
    {
        /* Never run ADC calibration, encoder bring-up, PWM start, motor
         * control or automatic IAP confirmation in this boot mode. */
        TIM1->BDTR &= ~TIM_BDTR_MOE;
        UART_SendLiteral("SAFE COMM BOOT: B1 held; motor and IAP confirmation disabled\r\n");

        if (Router_Init(ROUTER_LOCAL_NODE_ID) == 0U)
        {
            UART_SendLiteral("SAFE COMM: Router init failed\r\n");
            Error_Handler();
        }
        if (EspLink_Init() == 0U)
        {
            UART_SendLiteral("SAFE COMM: ESP link init failed\r\n");
            Error_Handler();
        }
        if (xTaskCreate(EspLink_Task, "EspLink", 512U, NULL, 1U, NULL) != pdPASS)
        {
            UART_SendLiteral("SAFE COMM: ESP task create failed\r\n");
            Error_Handler();
        }
        Router_RegisterPortTx(ROUTER_PORT_ESP32, EspLink_RouterTx);
        if (xTaskCreate(SafeCommTask, "SafeComm", 512U, NULL, 1U, NULL) != pdPASS)
        {
            UART_SendLiteral("SAFE COMM: router task create failed\r\n");
            Error_Handler();
        }
        UART_SendLiteral("SAFE COMM: discovery-only Router/ESP ready; CTRL_SD remains LOW\r\n");
        vTaskDelete(NULL);
    }

    UART_SendLiteral(
        "\r\n"
        "==========================================\r\n"
        "FreeRTOS generic motor-control API + TighteningTask test\r\n"
        "APP SLOT: A @ 0x08008000\r\n"
        "IAP FW V4 build: bootloader-owned metadata commit + V3 dual-copy\r\n"
        "StartupTask active\r\n"
        "Power stage starts DISABLED\r\n"
        "==========================================\r\n");

    {
        TightenParamsFlashLoadStatus_t param_load_status;
        char param_msg[160];

        recipe_state.kvs_ready =
            (PW_Kvs_Init() == PW_KVS_RESULT_OK) ? 1U : 0U;
        param_load_status = TightenParams_LoadFromFlash();

        if (param_load_status == PARAM_FLASH_LOAD_OK)
        {
            UART_SendFormatted(
                param_msg,
                sizeof(param_msg),
                "PARAM KVS: LOADED CRC32=0x%08lX RUNDOWN_RPM=%lu MIGRATED=%u\r\n",
                (unsigned long)recipe_state.last_crc32,
                (unsigned long)recipe_state.params.rundown_rpm,
                (unsigned int)recipe_state.kvs_migrated);
        }
        else
        {
            TightenParams_ResetDefaults(&recipe_state.params);
            recipe_state.flash_valid = 0U;
            recipe_state.dirty = 0U;
            recipe_state.last_crc32 = 0U;

            UART_SendFormatted(
                param_msg,
                sizeof(param_msg),
                "PARAM KVS: NO VALID RECORD -> DEFAULTS RUNDOWN_RPM=%lu\r\n",
                (unsigned long)recipe_state.params.rundown_rpm);
        }

    }

#if defined(FOC_RUNDOWN240_CANDIDATE)
    TightenParams_ApplyRundown240Candidate();
#if defined(FOC_DOB_CONTACT20_OBSERVE10)
    UART_SendLiteral("DOB C20/O10: CONTACT=20rpm OBS_MIN=10rpm FB_MIN=20rpm RAM_ONLY=1\r\n");
#endif
    UART_SendLiteral("RUNDOWN240: RAM=240rpm TRIP=" FOC_RUNDOWN240_TRIP_TEXT "rpm SAVE=OFF; manual START\r\n");
#if defined(FOC_RUNDOWN240_TRAVEL20000)
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
    UART_SendLiteral("RUNDOWN240: TRAVEL=30000deg RAM only\r\n");
#else
    UART_SendLiteral("RUNDOWN240: TRAVEL=20000deg RAM only\r\n");
#endif
#endif
#endif

    /*
     * 1) ADC hardware calibration.
     */
    if (HAL_ADCEx_Calibration_Start(&hadc1, ADC_SINGLE_ENDED) != HAL_OK)
    {
        UART_SendLiteral("ADC1 hardware calibration FAILED\r\n");
        Error_Handler();
    }

    if (HAL_ADCEx_Calibration_Start(&hadc2, ADC_SINGLE_ENDED) != HAL_OK)
    {
        UART_SendLiteral("ADC2 hardware calibration FAILED\r\n");
        Error_Handler();
    }

    /*
     * 2) Static current zero with bridge disabled / PWM stopped.
     */
#if defined(FOC_ISOLATED_CONCURRENCY) || defined(FOC_PROTECTED_CLOSED_LOOP)
    /* No regular-ADC baseline: qualify zero using the actual injected chain. */
#else
    if (ADC_CurrentZeroCalibrate() != HAL_OK)
    {
        UART_SendLiteral("STATIC CURRENT ZERO CAL FAILED\r\n");
#if defined(CAN_STATUS_TELEMETRY)
        UART_SendLiteral("MOTOR LOCKED; CAN fault telemetry active until reboot\r\n");
        StartupZeroCalFaultCommsLoop();
#endif
        Error_Handler();
    }
#endif

    ADC_AnalogBootSnapshot();
    ADC_VrefBootSnapshot();

    /*
     * 3) Encoder sanity check.
     */
    if (AS5047P_StartupCheck() != HAL_OK)
    {
        UART_SendLiteral(
            "AS5047P STARTUP CHECK FAILED - POWER STAGE STAYS OFF\r\n");
        PowerStage_Disable();
        Error_Handler();
    }

    /*
     * 4) Configure and arm the 20 kHz injected ADC chain.
     */
    if (ADC_ConfigIndependentSameTrigger() != HAL_OK)
    {
        UART_SendLiteral("ADC1/ADC2 SAME-TRIGGER CONFIG ERROR\r\n");
        Error_Handler();
    }

    UART_SendLiteral(
        "ADC1/ADC2 independent same-trigger mode configured\r\n"
        "Both injected groups use TIM1 TRGO2 rising edge\r\n");

#if defined(FOC_ADC_WINDOW)
    if (!FocAdcStatisticsTask_Start())
    {
        PowerStage_Disable();
        PWM_StopAll();
        UART_SendLiteral("ADC statistics static task CREATE FAILED\r\n");
        Error_Handler();
    }
#endif
    if (HAL_ADCEx_InjectedStart(&hadc2) != HAL_OK)
    {
        UART_SendLiteral("ADC2 INDEPENDENT INJECTED ARM ERROR\r\n");
        Error_Handler();
    }

    if (HAL_ADCEx_InjectedStart_IT(&hadc1) != HAL_OK)
    {
        UART_SendLiteral("ADC1 INDEPENDENT INJECTED START ERROR\r\n");
        Error_Handler();
    }

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    if (!ProtectedLoop_Init()) {
        UART_SendLiteral("PROTECTED MOTOR ZERO FAILED: output locked; no retry\r\n");
        ProtectedLoop_EmergencyOff(CL_BAD_ZERO);
    }
#elif defined(FOC_ISOLATED_CONCURRENCY)
    if (!IsolatedBench_Start(30000U))
    {
        UART_SendLiteral("ISOLATED BENCH START FAILED\r\n");
        IsolatedZero_Fail(FOC_ZERO_BAD_CONFIG);
    }
#else
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    PWM_StartAll();
#endif

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    UART_SendLiteral("PROTECTED MOTOR: boot outputs OFF; internal trigger only\r\n");
#elif defined(FOC_ISOLATED_CONCURRENCY)
    UART_SendLiteral("Internal trigger only; physical outputs remain disabled\r\n");
#else
    UART_SendLiteral(
        "PWM started at 50/50/50\r\n"
        "Checking 20kHz ADC injected chain...\r\n");
#endif

    seq_start = injected_seq_count;
    vTaskDelay(pdMS_TO_TICKS(100U));
    seq_delta = injected_seq_count - seq_start;

    UART_SendFormatted(msg, sizeof(msg),
             "Injected IRQ count/100ms=%lu\r\n",
             (unsigned long)seq_delta);

#if defined(FOC_ISOLATED_CONCURRENCY) || defined(FOC_PROTECTED_CLOSED_LOOP)
    /* 100 ms should contain 2000 pairs; do not qualify a much slower chain. */
    if (seq_delta < 1800U || seq_delta > 2200U)
#else
    if (seq_delta < 500U)
#endif
    {
        UART_SendLiteral("ERROR: injected trigger/IRQ count too low\r\n");
        PowerStage_Disable();
        PWM_StopAll();
#if defined(FOC_PROTECTED_CLOSED_LOOP)
        /* Keep the faulted read-only console available; boot health refuses
         * confirmation and uses the existing bounded rollback path. */
        ProtectedLoop_EmergencyOff(CL_BAD_ADC);
#elif defined(FOC_ISOLATED_CONCURRENCY)
        IsolatedZero_Fail(FOC_ZERO_RATE);
#else
        Error_Handler();
#endif
    }

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    UART_SendLiteral(cl_session.state==CL_READY ?
#if defined(FOC_RUNDOWN240_CANDIDATE)
        "RUNDOWN240 READY: local START only; 12s lease; no boot actuation\r\n" :
#else
#if defined(FOC_LATEST_ORIGINAL_FSM)
        "LATEST BACKEND / ORIGINAL FSM: explicit local START; 20 rpm / 400 ms qualification envelope; no boot actuation\r\n" :
#else
        "PROTECTED MOTOR READY: local MOTOR TEST SPEED only; 20 rpm / 400 ms; no boot actuation\r\n" :
#endif
#endif
        "PROTECTED MOTOR LOCKED: startup failed, no power admission\r\n");
#elif defined(FOC_ISOLATED_CONCURRENCY)
    IsolatedZero_Wait();
    UART_SendLiteral("ISOLATED CONCURRENCY: compute only; SD=MOE=CCER=0; 30s boot fixture\r\n");
#else
    /*
     * 5) Enable the bridge ONLY with all three PWM duties at 50%.
     *    Equal phase commands mean zero commanded line-line voltage.
     */
    foc_enable = 0U;
    PWM_SetDuty(0.5f, 0.5f, 0.5f);
    PowerStage_Enable();

    UART_SendLiteral(
        "\r\nCTRL_SD=HIGH\r\n"
        "Bridge enabled at 50/50/50, FOC still OFF, Iq_ref=0\r\n");

    /*
     * Give gate driver / current-sense circuitry a short settling time.
     */
    vTaskDelay(pdMS_TO_TICKS(50U));

    /*
     * 6) Measure current offsets again in the real PWM-switching environment.
     */
    if (ADC_RunZeroCalibrate() != HAL_OK)
    {
        UART_SendLiteral("PWM-ON RUN ZERO CAL ERROR\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * 7) Refresh encoder immediately before closing the current loop.
     */
    {
        uint16_t raw_enc = 0U;

        if (AS5047P_ReadAngle(&raw_enc) != HAL_OK)
        {
            UART_SendLiteral("ENCODER READ FAILED BEFORE FOC ENABLE\r\n");
            foc_enable = 0U;
            PowerStage_Disable();
            PWM_StopAll();
            Error_Handler();
        }

        encoder_raw = raw_enc;
        encoder_theta_e = Encoder_ElectricalAngleRad(raw_enc);
        encoder_theta_e_pred = encoder_theta_e;
        encoder_prev_raw = raw_enc;
        encoder_prev_valid = 1U;
        encoder_speed_rpm = 0.0f;
        encoder_omega_e_rad_s = 0.0f;
        encoder_rpm_instant = 0.0f;
        encoder_speed_dt_accum_s = 0.0f;
        encoder_speed_glitch_count = 0U;
        encoder_speed_glitch_streak = 0U;
        encoder_valid = 1U;
    }

    /*
     * 8) Reset current-controller state and explicitly force zero torque.
     */
    FOC_ResetController();

    foc_fault = 0U;
    foc_fault_reason = 0U;
    FaultDiag_Clear();
    adc_fault = 0U;

    foc_id_ref_A = 0.0f;
    foc_iq_ref_A = 0.0f;

    /*
     * 9) Enable ONLY the 20 kHz current controller.
     *
     * The 1 kHz position/speed outer-loop function is NOT called in this
     * build, so no intentional torque command can be generated.
     */
    foc_enable = 1U;

    MotorControl_SetIdle();

    UART_SendLiteral(
        "\r\n"
        "==========================================\r\n"
        "GENERIC MOTOR-CONTROL API ENABLED\r\n"
        "Current loop    : ADC ISR @ 20kHz\r\n"
        "Motor control   : MotorControlTask @ 1kHz\r\n"
        "Application     : TighteningTask @ 100Hz, command-driven\r\n"
        "Router          : Stage3 dynamic RouterTask @ 5ms, LOCAL + UART1\r\n"
        "Discovery       : HELLO/ANNOUNCE 5s + node/route aging 15s\r\n"
        "Loop guard      : TTL + duplicate cache + reflected-self suppression\r\n"
        "Reply routing   : routed Protocol request -> routed synchronous reply\r\n"
        "Protocol        : Router LOCAL packet queue -> ProtocolTask @ 5ms\r\n"
        "Monitor         : 3s IDLE / 1s ACTIVE\r\n"
        "UART TX runtime : DMA1_CH1 + 8KiB ring\r\n"
        "UART RX runtime : DMA1_CH2 circular + 512B RX ring\r\n"
        "Protocol V2     : <REQ_ID> <COMMAND>, correlated replies\r\n"
        "Parameters      : GET/SET + pw_kvs dual-copy wear leveling + CRC\r\n"
        "IAP FW          : inactive-slot write + CRC32 + pending trial\r\n"
        "Boot health     : 5s continuous gate + auto confirm + fail reset\r\n"
        "Commands        : HELP / PING / STATUS / START / STOP / RESULT\r\n"
        "Modes           : IDLE / POSITION / SPEED / IQ\r\n"
        "Test            : one tightening cycle per START command\r\n"
        "RUNDOWN         : runtime parameter, SPEED Iq limit +/-0.40A\r\n"
        "Contact         : runtime thresholds\r\n"
        "SEATING         : runtime current/time\r\n"
        "TIGHTENING      : runtime stage currents/times\r\n"
        "HOLD            : runtime current/time\r\n"
        "Torque abort    : runtime speed/travel limits\r\n"
        "UART            : CTRL/DET/RAW + DriveIq + TRV/PTRV + C/CT\r\n"
        "Result log      : 100Hz IqAvg/IqMax/CtrlMax/DetAvg/dAng\r\n"
        "Start behavior  : power-up stays IDLE; no automatic rundown\r\n"
        "Phase trip      : 4.0A; powered validation pending\r\n"
        "==========================================\r\n");

#endif
#if defined(FOC_ORIGINAL_CLOSED_LOOP_UPDATED)
    {
        static char profile[256];
        OriginalClosedLoop_FormatProfile(profile, sizeof(profile),
            (uint32_t)(FOC_CURRENT_TRIP_A * 1000.0f + 0.5f), RUN_ZERO_MAX_DELTA_COUNTS,
            (uint32_t)(FOC_TS_S * 1000000.0f + 0.5f),
            (uint32_t)(MOTOR_SPEED_IQ_LIMIT_A * 1000.0f + 0.5f),
            (uint32_t)(MOTOR_DIRECT_IQ_LIMIT_A * 1000.0f + 0.5f),
            (uint32_t)(FOC_VOLTAGE_LIMIT_V * 1000.0f + 0.5f));
        UART_SendString(profile);
    }
#endif
    /*
     * Startup/calibration logging above intentionally used the proven blocking
     * UART path.  From this point onward, switch normal RTOS logging to
     * DMA + ring buffer.
     */
    if (UART_Async_Init(&hlpuart1) != HAL_OK)
    {
        static const char warn[] =
            "WARNING: UART async TX init failed; runtime logs stay blocking\r\n";

        HAL_UART_Transmit(&hlpuart1,
                          (uint8_t *)warn,
                          (uint16_t)(sizeof(warn) - 1U),
                          HAL_MAX_DELAY);
    }
    else
    {
        UART_AsyncSelfTestInfo_t info;
        UART_AsyncSelfTestResult_t test_result;
        char dma_dbg[320];

        /*
         * This blocking line proves UART_Async_Init() returned HAL_OK.
         */
        static const char ok[] =
            "UART ASYNC INIT OK: running DIRECT DMA self-test...\r\n";

        HAL_UART_Transmit(&hlpuart1,
                          (uint8_t *)ok,
                          (uint16_t)(sizeof(ok) - 1U),
                          HAL_MAX_DELAY);

        /*
         * Bypass RingBuffer and UartTx task completely.
         * This isolates the raw HAL UART-DMA path.
         */
        test_result =
            UART_Async_RunDirectDmaSelfTest(&info);

        snprintf(
            dma_dbg,
            sizeof(dma_dbg),
            "UART DMA SELFTEST RESULT=%u HAL=%u "
            "UG:%lu->%lu DG:%lu->%lu "
            "CNDTR:%lu->%lu REQ=%lu CCR=0x%08lX CR3=0x%08lX\r\n",
            (unsigned int)test_result,
            (unsigned int)info.start_status,
            (unsigned long)info.uart_gstate_before,
            (unsigned long)info.uart_gstate_after,
            (unsigned long)info.dma_state_before,
            (unsigned long)info.dma_state_after,
            (unsigned long)info.dma_remaining_before,
            (unsigned long)info.dma_remaining_after,
            (unsigned long)info.dma_request,
            (unsigned long)info.dma_ccr,
            (unsigned long)info.uart_cr3);

        /*
         * The self-test aborts the UART DMA on timeout, so blocking UART is
         * safe here for all result paths.
         */
        HAL_UART_Transmit(&hlpuart1,
                          (uint8_t *)dma_dbg,
                          (uint16_t)strlen(dma_dbg),
                          HAL_MAX_DELAY);

        if (test_result == UART_ASYNC_SELFTEST_PASS)
        {
            static const char pass[] =
                "UART DMA SELFTEST PASS -> enabling ring-buffer runtime TX\r\n";

            HAL_UART_Transmit(&hlpuart1,
                              (uint8_t *)pass,
                              (uint16_t)(sizeof(pass) - 1U),
                              HAL_MAX_DELAY);

            UART_SendLiteral(
                "UART ASYNC TX: initialized; runtime gate opens after StartupTask exits\r\n");
        }
        else
        {
            static const char fail[] =
                "UART DMA SELFTEST FAILED -> do not trust async runtime yet\r\n";

            HAL_UART_Transmit(&hlpuart1,
                              (uint8_t *)fail,
                              (uint16_t)(sizeof(fail) - 1U),
                              HAL_MAX_DELAY);
        }
    }

    /*
     * Layer 1B RX path. The TX path remains unchanged and already validated.
     */
    if (UART_RxDma_Init(&hlpuart1) != HAL_OK)
    {
        UART_SendLiteral(
            "WARNING: UART RX DMA init failed; commands unavailable\r\n");
    }
    else
    {
        UART_SendLiteral(
            "UART RX DMA: DMA1_CH2 circular + RX ring READY\r\n");
    }

    /*
     * Router Core owns transport ingress. ProtocolTask now consumes only the
     * LOCAL endpoint queue, so legacy commands remain compatible while routed
     * packets can later arrive from UART/USB/Socket adapters.
     */
    if (Router_Init(ROUTER_LOCAL_NODE_ID) == 0U)
    {
        UART_SendLiteral("Router_Init FAILED\r\n");
        Error_Handler();
    }

    Router_RegisterPortTx(
        ROUTER_PORT_UART1,
        Router_Uart1Tx);

    /* Optional ESP32-S3 discovery transport on USART1 PA9/PA10. Ingress
     * remains HELLO/ANNOUNCE only: no motor, parameter or IAP commands. */
    if (EspLink_Init() != 0U)
    {
        if (xTaskCreate(EspLink_Task,
                        "EspLink",
                        512U,
                        NULL,
                        1U,
                        NULL) == pdPASS)
        {
            Router_RegisterPortTx(ROUTER_PORT_ESP32,
                                  EspLink_RouterTx);
            UART_SendLiteral("ESP32 LINK READY (PA9/PA10)\r\n");
        }
        else
        {
            EspLink_Deinit();
            UART_SendLiteral("ESP32 LINK: task unavailable; link disabled\r\n");
        }
    }
    else
    {
        UART_SendLiteral("ESP32 LINK: init unavailable; link disabled\r\n");
    }

    protocol_async_event_queue = xQueueCreate(
        PROTOCOL_ASYNC_EVENT_QUEUE_DEPTH,
        sizeof(ProtocolAsyncEvent_t));

    if (protocol_async_event_queue == NULL)
    {
        UART_SendLiteral("Protocol async event queue CREATE FAILED\r\n");
        Error_Handler();
    }

    modbus_request_queue = xQueueCreate(MODBUS_QUEUE_DEPTH,
                                         sizeof(ModbusJob_t));
    modbus_completion_queue = xQueueCreate(MODBUS_QUEUE_DEPTH,
                                            sizeof(ModbusCompletion_t));
    if ((modbus_request_queue == NULL) || (modbus_completion_queue == NULL))
    {
        UART_SendLiteral("Modbus queues CREATE FAILED\r\n");
        Error_Handler();
    }

    memset(protocol_reliable_events, 0, sizeof(protocol_reliable_events));
    memset(protocol_reliable_rx_cache, 0, sizeof(protocol_reliable_rx_cache));
    protocol_reliable_next_eid = 1U;
    protocol_reliable_rx_cache_cursor = 0U;

    UART_SendLiteral(
        "ROUTER CORE STAGE3 + RELIABLE ASYNC EVT STAGE4.3: NODE=1 LOCAL,UART1 READY\r\n");

    /*
     * High-priority deterministic motor-control task.
     */
    if (xTaskCreate(MotorControlTask,
                    "MotorCtrl",
                    768U,
                    NULL,
                    4U,
                    &motor_control_task_handle) != pdPASS)
    {
        UART_SendLiteral("MotorControlTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Application-layer tightening task.
     *
     * Priority is intentionally below MotorControlTask.  It can change motor
     * commands, but cannot preempt the 1 kHz control service indefinitely.
     */
    if (xTaskCreate(TighteningTask,
                    "Tighten",
                    768U,
                    NULL,
                    3U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("TighteningTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Transport ingress and packet forwarding. RouterTask owns UART RX DMA
     * consumption; ProtocolTask no longer reads the UART ring directly.
     */
    if (xTaskCreate(RouterTask,
                    "Router",
#if defined(ROUTER_READ_ONLY_NETWORK)
                    /* Hardware acceptance: 2 KiB overflowed while formatting
                     * a diagnostic reply plus R1 TX. Cortex-M4 units = words.
                     * Reserve 4 KiB; measure the stack margin under live load. */
                    1024U,
#else
                    512U,
#endif
                    NULL,
                    2U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("RouterTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Local protocol endpoint. Same priority as Router/UartTx and below the
     * application and motor-control tasks.
     */
    if (xTaskCreate(ProtocolTask,
                    "Protocol",
                    1024U,
                    NULL,
                    2U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("ProtocolTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

#if defined(TIGHTEN_SYNTHETIC_BENCH)
    synthetic_task_handle = xTaskCreateStatic(SyntheticTask, "Synthetic", 1024U,
                    NULL, 1U, synthetic_task_stack, &synthetic_task_tcb);
    if (synthetic_task_handle == NULL)
    {
        UART_SendLiteral("SyntheticTask CREATE FAILED\r\n");
        IsolatedBench_Stop(3U);
        Error_Handler();
    }
    UART_SendLiteral("SYNTHETIC FIXTURE READY: local SIM commands; MODEL ONLY; no motor output\r\n");
#endif
    /* Low-priority owner of USART3; only results return to ProtocolTask. */
    if (xTaskCreate(ModbusTask,
                    "Modbus",
                    512U,
                    NULL,
                    0U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("ModbusTask CREATE FAILED\r\n");
        Error_Handler();
    }

    /*
     * Low-priority UART diagnostics task. Keeping UART out of MotorControlTask
     * prevents serial work from disturbing the 1 kHz control loop.
     */
    if (xTaskCreate(MonitorTask,
                    "Monitor",
                    768U,
                    NULL,
                    1U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("MonitorTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Pending/trial firmware gets a continuous health window before it may
     * become confirmed.
     */
    if (xTaskCreate(BootHealthTask,
                    "BootHealth",
                    512U,
                    NULL,
                    1U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("BootHealthTask CREATE FAILED\r\n");
        foc_enable = 0U;
        PowerStage_Disable();
        PWM_StopAll();
        Error_Handler();
    }

    /*
     * Still use blocking UART for this final StartupTask line. Only after it
     * has been emitted do we arm the runtime async path, then immediately
     * delete this priority-5 task so the lower-priority UART TX service can
     * actually run.
     */
    UART_SendLiteral(
        "StartupTask complete -> MotorControlTask + TighteningTask + RouterTask + ProtocolTask + MonitorTask + BootHealthTask + PwLogTask running\r\n");

    if (PW_Log_Init() == 0)
    {
        UART_SendLiteral("PW LOG INIT FAILED\r\n");
    }
    else if (PW_LogRouter_Init() == 0)
    {
        UART_SendLiteral("PW LOG ROUTER INIT FAILED\r\n");
    }
    g_uart_async_runtime_enable = 1U;
#if defined(CAN_LOG_STREAM)
    if (PW_CanLog_Init() == 0U) UART_SendLiteral("PW CAN LOG INIT FAILED\r\n");
#endif
    PW_SmokeTest();
    (void)PW_Allocator_RunSelfTest();
#if !defined(PW_TARGET_UNIT_TESTS_DISABLED)
    PW_UnitTestsRun();
#endif
    PW_ThreadSmokeStart();
    PW_Rpc_Init();
#if defined(UART_FIRMWARE_TRANSFER)
    PW_UartFirmwareTransfer_Init();
#endif
#if defined(CAN_RPC_READ_ONLY)
    if (!PW_CanRpc_Init()) UART_SendLiteral("CAN READONLY RPC INIT FAILED\r\n");
#endif
    vTaskDelete(NULL);
}

