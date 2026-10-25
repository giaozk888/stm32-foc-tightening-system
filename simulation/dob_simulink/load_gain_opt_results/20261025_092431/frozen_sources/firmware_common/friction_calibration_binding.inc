/* Diagnostic A only. Reuse exactly the existing admission, current/speed PI,
 * S-curve, one-shot lease and ADC/TIM7 closures. No new power-enable writes. */
static uint8_t TighteningIntent_PrecheckOnly(void)
{
    return (uint8_t)(friction_calibration.admitting &&
        motor_control_mode==MOTOR_MODE_IDLE && !friction_calibration.active);
}
static void TighteningIntent_PrintStatus(uint32_t request_id)
{
    char msg[160];
    Protocol_SendFormatted(msg,sizeof msg,
        "0 EVT FCAL REQ=%lu RPM=%ld ACTIVE=%u DONE=%u PASS=%u\r\n",
        (unsigned long)request_id,(long)friction_calibration.rpm,
        friction_calibration.active,friction_calibration.finished,friction_calibration.passed);
}
static void FrictionCalibration_Observe(float dt)
{
    uint32_t seq=cl_seq;
    __DMB();
    float iq=foc_iq_A,id=foc_id_A,angle=encoder_position_deg;
    uint8_t healthy=(uint8_t)(cl_session.state==CL_RUNNING && !adc_fault && !foc_fault &&
        cl_safety.protection.result==FOC_OC_CLEAR &&
        cl_safety.validation.last_path==FOC_CURRENT_PATH_NORMAL &&
        !speed_accel_ff_frame.saturated && !speed_friction_enabled);
    __DMB();
    healthy=(uint8_t)(healthy && seq==cl_seq);
    Fcal_Observe(&friction_calibration,speed_accel_ff_frame.speed_ref_rpm,
        encoder_speed_rpm,speed_scurve.acceleration_rpm_s,iq,foc_iq_ref_A,
        id,angle,dt,healthy);
}
__attribute__((optimize("Os")))
static uint8_t FrictionCalibration_Command(const char *cmd,char *out,size_t size)
{
#if defined(FOC_MECHANICAL_MOTION_DIAG)
    if (strncmp(cmd,"MOTOR TEST MECH ",16U)) return 0;
#else
    if (strncmp(cmd,"MOTOR TEST FCAL ",16U)) return 0;
#endif
#if defined(FOC_MECHANICAL_DOB_SHADOW)
#if defined(FOC_ID_STEADY_STATS)
    if (IdSteady_Command(cmd,out,size)) return 1;
#endif
    if (MechanicalDob_Command(cmd,out,size)) return 1;
    if (!strcmp(cmd,"MOTOR TEST MECH DIRECTION")) {
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
        snprintf(out,size,"OK MECH DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=%u",(unsigned)dob_feedback.enabled);return 1;
#else
        snprintf(out,size,"OK MECH DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=0");return 1;
#endif
    }
#endif
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
#if defined(FOC_MECHANICAL_REVERSE_IDENT_DIAG)
    if (!strcmp(cmd,"MOTOR TEST MECH DIRECTION")) {
        snprintf(out,size,"OK MECH REVERSE_IDENT=1 SIGN=-1 GRID_RPM=600,700,800 DOB_CONTROL=0");
        return 1;
    }
#endif
    if (!strcmp(cmd,"MOTOR TEST MECH LIMITS")) {
#if defined(FOC_ENCODER_CONTROL_ADMISSION_FIX)
#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
        snprintf(out,size,"OK MECH API_RPM=%u TRIP_RPM=%u IQ_LIMIT_MA=%u TRAVEL_DEG=%u DRIVE_MS=%u STOP_MS=%u LEASE_US=%u PLAUSIBLE_RPM=%u REJECT_BUSY=1 OBS_AFTER_ACK=1",
#else
        snprintf(out,size,"OK MECH API_RPM=%u TRIP_RPM=%u IQ_LIMIT_MA=%u TRAVEL_DEG=%u DRIVE_MS=%u STOP_MS=%u LEASE_US=%u PLAUSIBLE_RPM=%u REJECT_BUSY=1",
#endif
#else
        snprintf(out,size,"OK MECH API_RPM=%u TRIP_RPM=%u IQ_LIMIT_MA=%u TRAVEL_DEG=%u DRIVE_MS=%u STOP_MS=%u LEASE_US=%u",
#endif
            (unsigned)MOTOR_SPEED_API_LIMIT_RPM,CL_OVERSPEED_RPM,
            (unsigned)(MOTOR_SPEED_IQ_LIMIT_A*1000.0f+.5f),
            FOC_RUNDOWN240_MAX_TRAVEL_DEG,FCAL_DRIVE_MS,FCAL_STOP_MS,CL_MAX_US
#if defined(FOC_ENCODER_CONTROL_ADMISSION_FIX)
            ,(unsigned)SPEED_INSTANT_PLAUSIBLE_RPM
#endif
            );return 1;
    }
#endif
#if defined(FOC_FRICTION_HIGH_SPEED_GRID)
    if (!strcmp(cmd,"MOTOR TEST FCAL LIMITS")) {
        snprintf(out,size,"OK FCAL API_RPM=%u TRIP_RPM=%u IQ_LIMIT_MA=%u GRID=HIGH",
            (unsigned)MOTOR_SPEED_API_LIMIT_RPM,CL_OVERSPEED_RPM,
            (unsigned)(MOTOR_SPEED_IQ_LIMIT_A*1000.0f+.5f));return 1;
    }
#endif
#if defined(FOC_READY_TIMESTAMP_SNAPSHOT)
    if (!strcmp(cmd,"MOTOR TEST MECH READY")) {
        ProtectedReadinessReject r;
        taskENTER_CRITICAL();r=cl_ready_reject;taskEXIT_CRITICAL();
        snprintf(out,size,"OK MECH READY FIX=1 VALID=%lu FAIL=0x%08lX CLOCK=%lu ADC=%lu NOW=%lu AGE=%lu RPM=%ld ATTEMPT=%lu",
            (unsigned long)r.valid,(unsigned long)r.check.failed,(unsigned long)r.check.clock_valid,
            (unsigned long)r.check.adc_us,(unsigned long)r.check.now_us,(unsigned long)r.check.age_us,
            (long)r.rpm,(unsigned long)r.attempt);
        return 1;
    }
#endif
    int32_t rpm=0;
    if (Fcal_Parse(cmd,&rpm)) {
        taskENTER_CRITICAL();
#if defined(FOC_READY_TIMESTAMP_SNAPSHOT)
        cl_ready_check=(ProtectedReadiness){0};++cl_ready_attempts;
        uint8_t ready=(uint8_t)(CL_READY_REQUIRE(!friction_calibration.used,CL_READY_FCAL_USED) &&
            CL_READY_REQUIRE(!cl_session.used,CL_READY_USED) &&
#if defined(FOC_MECHANICAL_MOTION_DIAG)
            CL_READY_REQUIRE(cl_session.state==CL_READY,CL_READY_STATE) && ProtectedLoop_Ready() &&
            CL_READY_REQUIRE(speed_friction_enabled,CL_READY_FRICTION) &&
#else
            CL_READY_REQUIRE(cl_session.state==CL_READY,CL_READY_STATE) && ProtectedLoop_Ready() &&
            CL_READY_REQUIRE(!speed_friction_enabled,CL_READY_FRICTION) &&
#endif
            CL_READY_REQUIRE(motor_control_mode==MOTOR_MODE_IDLE,CL_READY_MODE) &&
            CL_READY_REQUIRE(!Tightening_IsBusy(),CL_READY_BUSY) &&
            CL_READY_REQUIRE(!tightening_start_request,CL_READY_START) &&
            CL_READY_REQUIRE(!tightening_stop_request,CL_READY_STOP) &&
            CL_READY_REQUIRE(!(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin),CL_READY_SD) &&
            CL_READY_REQUIRE(!(TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)),CL_READY_MOE) &&
            CL_READY_REQUIRE(!TIM1->CCER,CL_READY_CCER));
        if (!ready) cl_ready_reject=(ProtectedReadinessReject){cl_ready_check,rpm,cl_ready_attempts,1U};
#else
        uint8_t ready=(uint8_t)(!friction_calibration.used && !cl_session.used &&
#if defined(FOC_MECHANICAL_MOTION_DIAG)
            cl_session.state==CL_READY && ProtectedLoop_Ready() && speed_friction_enabled &&
#else
            cl_session.state==CL_READY && ProtectedLoop_Ready() && !speed_friction_enabled &&
#endif
            motor_control_mode==MOTOR_MODE_IDLE && !Tightening_IsBusy() &&
            !tightening_start_request && !tightening_stop_request &&
            !(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) &&
            !(TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) && !TIM1->CCER);
#endif
        if (ready) {
            friction_calibration=(FrictionCalibration){.used=1U,.queued=1U,.rpm=rpm};
        }
        taskEXIT_CRITICAL();
#if defined(FOC_MECHANICAL_MOTION_DIAG)
        snprintf(out,size,ready ? "OK MECH QUEUED RPM=%ld" : "ERR MECH NOT_READY",(long)rpm);
#else
        snprintf(out,size,ready ? "OK FCAL QUEUED RPM=%ld" : "ERR FCAL NOT_READY",(long)rpm);
#endif
        return 1;
    }
#if defined(FOC_MECHANICAL_MOTION_DIAG)
    if (strcmp(cmd,"MOTOR TEST MECH STATUS")) {
#else
    if (strcmp(cmd,"MOTOR TEST FCAL STATUS")) {
#endif
        snprintf(out,size,"ERR FCAL COMMAND");return 1;
    }
    FrictionCalibration s;
    taskENTER_CRITICAL();s=friction_calibration;taskEXIT_CRITICAL();
#if defined(FOC_MECHANICAL_MOTION_DIAG)
    snprintf(out,size,"OK MECH RPM=%ld USED=%u ACTIVE=%u DONE=%u LEGACY_FCAL_PASS=%u N=%lu REJECT=%lu VALID_MS=%lu FRIC=%u DRIVE_MS=5000 LEASE_US=12000000",
#else
    snprintf(out,size,"OK FCAL RPM=%ld USED=%u ACTIVE=%u DONE=%u PASS=%u N=%lu REJECT=%lu VALID_MS=%lu FRIC=%u DRIVE_MS=5000 LEASE_US=12000000",
#endif
        (long)s.rpm,s.used,s.active,s.finished,s.passed,(unsigned long)s.valid,
        (unsigned long)s.reject,(unsigned long)(1000*s.valid_s),speed_friction_enabled);
    return 1;
}
__attribute__((optimize("Os")))
static void TighteningTask(void *argument)
{
    (void)argument;TickType_t wake=xTaskGetTickCount();
    MotorControl_SetIdle();
#if defined(FOC_MECHANICAL_MOTION_DIAG)
    UART_SendLiteral("MECH_IDENT_DIAGNOSTIC: manual signed point; fixed compensation; no START\r\n");
#else
    UART_SendLiteral("FCAL_DIAGNOSTIC: manual single point; FRIC OFF; no START\r\n");
#endif
    for (;;) {
        FrictionCalibration *s=&friction_calibration;
        if (tightening_start_request || tightening_stop_request) {
            /* Normal START is never converted to calibration motion. STOP
             * cannot leave a queued command that would restart later. */
            uint32_t req=tightening_start_request_id;
            uint8_t start=tightening_start_request;
            tightening_start_request=tightening_stop_request=0U;
            if (s->active || s->queued) {
                ProtectedLoop_Stop();s->queued=s->active=0U;Fcal_Finish(s,0U);
            }
            if (start) Protocol_SendError(req,PROTO_ERR_BUSY,"FCAL_USE_EXPLICIT_COMMAND");
        }
        if (s->active && cl_session.state!=CL_RUNNING) {
            s->active=0U;MotorControl_SetIdle();Fcal_Finish(s,0U);
        }
        if (s->queued) {
            if (!s->prepared) { s->encoder_before=cl_outer_n;s->prepared=1U; }
            else if (cl_outer_n!=s->encoder_before) {
                s->admitting=1U;
                uint8_t admitted=LatestOriginal_Admit();
                s->admitting=s->queued=0U;
                if (!admitted) { ProtectedLoop_Stop();Fcal_Finish(s,0U); }
            }
        }
        if (s->active) {
            uint32_t elapsed=(uint32_t)(AS5047P_DmaNowUs()-cl_session.start_us)/1000U;
            uint8_t no_rotation=(uint8_t)(elapsed<FCAL_DRIVE_MS &&
                TightenRundown_Update(&tightening_rundown,elapsed,(float)s->rpm,
                    encoder_speed_rpm,encoder_speed_detect_rpm,encoder_position_deg,
                    foc_iq_ref_A,encoder_valid));
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
            /* Unlike the plateau estimator (finished at 5s), travel protection
             * must keep observing the actual shaft throughout deceleration. */
            uint8_t travel=(uint8_t)(s->angle_initialized &&
                fabsf(encoder_position_deg-s->start_angle)>FOC_RUNDOWN240_MAX_TRAVEL_DEG);
#else
            uint8_t travel=(uint8_t)(fabsf(s->net_travel)>20000.0f);
#endif
            if (no_rotation || travel) {
                ProtectedLoop_Stop();MotorControl_SetIdle();s->active=0U;Fcal_Finish(s,0U);
                FaultDiag_Capture(FOC_DIAG_PROCESS,
                    no_rotation ? TIGHTEN_OUTCOME_NO_ROTATION : TIGHTEN_OUTCOME_ABORT,
                    FOC_TO_NONE,elapsed,no_rotation ? RUNDOWN_START_TIMEOUT_MS :
#if defined(FOC_MECHANICAL_HIGH_SPEED_DIAG)
                    FOC_RUNDOWN240_MAX_TRAVEL_DEG);
#else
                    20000U);
#endif
            }
            if (s->active && elapsed>=FCAL_DRIVE_MS) {
                if (!s->finished) Fcal_Finish(s,(uint8_t)(!adc_fault && !foc_fault));
                MotorControl_SetSpeed(0.0f); /* Existing S-curve performs deceleration. */
                if (fabsf(encoder_speed_rpm)<=2.0f) s->stop_good_ms+=10U;
                else s->stop_good_ms=0U;
                if (s->stop_good_ms>=100U || elapsed>=FCAL_STOP_MS) {
                    if (s->stop_good_ms<100U) s->passed=0U;
                    ProtectedLoop_Stop();s->active=0U;MotorControl_SetIdle();
                }
            }
        }
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(10U));
    }
}
