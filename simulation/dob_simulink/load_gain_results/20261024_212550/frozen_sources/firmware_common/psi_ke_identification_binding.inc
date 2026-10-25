/* Exclusive diagnostic Task; normal control math/protection remains owned by
 * existing ADC/current/speed/S-curve code. No new power-enable transaction. */
static uint8_t TighteningIntent_PrecheckOnly(void)
{
    return psi_ident.admitting && motor_control_mode==MOTOR_MODE_IDLE && !psi_ident.active;
}
static void TighteningIntent_PrintStatus(uint32_t request_id)
{
    char msg[128];
    Protocol_SendFormatted(msg,sizeof msg,"0 EVT PSI REQ=%lu RPM=%ld ACTIVE=%u DONE=%u\r\n",
        (unsigned long)request_id,(long)psi_ident.rpm,psi_ident.active,psi_ident.finished);
}
__attribute__((optimize("Os")))
static uint8_t PsiIdent_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST PSI ",15U)) return 0U;
    const char *arg=cmd+15U;
    if (!strcmp(arg,"PLAN")) {
        snprintf(out,size,"OK PSI RS_UOHM=%ld LD_NH=%ld PP=%u MIN_RPM=50 API_RPM=%u TRIP_RPM=%u POINTS=100,200,300,400 DRIVE_MS=5000 WINDOW_MS=2000 LEASE_US=12000000 BEMF_AUTO_APPLY=0",
            (long)(CURRENT_PI_CANDIDATE_RS_OHM*1e6f+.5f),
            (long)(CURRENT_PI_CANDIDATE_LD_H*1e9f+.5f),POLE_PAIRS,
            (unsigned)MOTOR_SPEED_API_LIMIT_RPM,CL_OVERSPEED_RPM);return 1U;
    }
    int32_t rpm=!strcmp(arg,"RUN 100") ? 100 : !strcmp(arg,"RUN 200") ? 200 :
                !strcmp(arg,"RUN 300") ? 300 : !strcmp(arg,"RUN 400") ? 400 : 0;
    if (rpm) {
        if (!PsiIdent_Allowed(rpm,MOTOR_SPEED_API_LIMIT_RPM,CL_OVERSPEED_RPM)) {
            snprintf(out,size,"OK PSI SKIPPED RPM=%ld REASON=EXISTING_SPEED_LIMIT",(long)rpm);return 1U;
        }
        taskENTER_CRITICAL();
        uint8_t ready=(uint8_t)(!psi_ident.used && !cl_session.used &&
            cl_session.state==CL_READY && ProtectedLoop_Ready() && !bemf_enabled &&
            motor_control_mode==MOTOR_MODE_IDLE && !Tightening_IsBusy() &&
            !tightening_start_request && !tightening_stop_request &&
            !(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) &&
            !(TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) && !TIM1->CCER);
        if (ready) psi_ident=(PsiIdentification){.used=1U,.queued=1U,.rpm=rpm};
        taskEXIT_CRITICAL();
        snprintf(out,size,ready ? "OK PSI QUEUED RPM=%ld" : "ERR PSI NOT_READY",(long)rpm);return 1U;
    }
    if (!strcmp(arg,"STATUS")) {
        snprintf(out,size,"OK PSI RPM=%ld USED=%u ACTIVE=%u DONE=%u PASS=%u STAGE=%lu N=%lu REJECT=%lu",
            (long)psi_ident.rpm,psi_ident.used,psi_ident.active,psi_ident.finished,psi_ident.passed,
            (unsigned long)psi_ident.stage,(unsigned long)psi_ident.valid,(unsigned long)psi_ident.reject);return 1U;
    }
    if (!strcmp(arg,"RESULT")) {
        /* Final result only: producer has stopped and will never overwrite
         * this one-shot result. Never snapshot a half-updated task aggregate. */
        if (psi_ident.active || !psi_ident.finished) {
            snprintf(out,size,"ERR PSI RESULT_NOT_FINISHED");return 1U;
        }
        PsiIdentification s;
        taskENTER_CRITICAL();s=psi_ident;taskEXIT_CRITICAL();
        float std=s.valid>1U ? sqrtf(fmaxf(0.0f,s.psi_m2/(float)(s.valid-1U))) : 0.0f;
        snprintf(out,size,"OK PSI DONE=%u PASS=%u N=%lu REJECT=%lu RPM_MRPM=%ld ID_UA=%ld IQ_UA=%ld VQ_UV=%ld BEMF_UV=%ld PSI_NWB=%ld STD_NWB=%ld WE_MRAD_S=%ld MODEL=COMMAND_VOLTAGE",
            s.finished,s.passed,(unsigned long)s.valid,(unsigned long)s.reject,
            (long)BemfWire_Scaled(s.mean[0],1e3f),(long)BemfWire_Scaled(s.mean[1],1e6f),
            (long)BemfWire_Scaled(s.mean[2],1e6f),(long)BemfWire_Scaled(s.mean[3],1e6f),
            (long)BemfWire_Scaled(s.mean[4],1e6f),(long)BemfWire_Scaled(s.mean[5],1e9f),
            (long)BemfWire_Scaled(std,1e9f),(long)BemfWire_Scaled(s.mean[6],1e3f));return 1U;
    }
    snprintf(out,size,"ERR PSI COMMAND");return 1U;
}
static void PsiIdent_ObserveTask(uint32_t now)
{
    PsiIdentification *s=&psi_ident;
    if (!s->active || s->finished || (uint32_t)(now-s->last_observe)<PSI_OBSERVE_US) return;
    /* Keep the 20 Hz sampling phase; assigning now every time would turn
     * a little 10 ms task jitter into repeated 60 ms sampling intervals. */
    if (!s->last_observe) s->last_observe=now;
    else {
        s->last_observe+=PSI_OBSERVE_US;
        if ((uint32_t)(now-s->last_observe)>=PSI_OBSERVE_US) s->last_observe=now;
    }
    FocBemfFrame b;
    uint8_t healthy;
    /* Coherent accepted ADC frame; NO mixing alternating UART replies. */
    uint32_t mask=__get_PRIMASK();__disable_irq();
    b=bemf_frame;
    healthy=(uint8_t)(cl_session.state==CL_RUNNING && b.valid && !adc_fault && !foc_fault &&
        cl_safety.protection.result==FOC_OC_CLEAR &&
        cl_safety.validation.last_path==FOC_CURRENT_PATH_NORMAL);
    __set_PRIMASK(mask);
    healthy=(uint8_t)(healthy && (uint32_t)(AS5047P_DmaNowUs()-b.source_us)<=PSI_MAX_FRAME_AGE_US);
    PsiIdentFrame f={.seq=b.seq,.us=b.source_us,.we=b.omega_e,.id=b.id,.iq=b.iq,
        .vd=b.vd,.vq=b.vq,.saturated=b.saturated,.fault=(uint32_t)(adc_fault || foc_fault || cl_flags)};
    PsiIdent_Calculate(&f,CURRENT_PI_CANDIDATE_RS_OHM,CURRENT_PI_CANDIDATE_LD_H,POLE_PAIRS);
    /* Window progression uses task time even for rejected stale frames;
     * the unchanged source timestamp stays attached to the ADC sequence. */
    PsiIdent_Observe(s,f,speed_ref_rpm,speed_scurve.acceleration_rpm_s,healthy,now);
    PsiIdent_Log(&s->latest);
}
__attribute__((optimize("Os")))
static void TighteningTask(void *argument)
{
    /* These existing normal-FSM entry points are intentionally dormant in
     * this exclusive mode. No-op references document that fact without
     * suppressing compiler diagnostics globally or retaining their code. */
    (void)Protocol_SendCycleEvent;(void)Protocol_SendDeferredStartError;
    (void)TighteningSession_Begin;(void)TighteningRepeat_StoreCurrentCycle;
    (void)TighteningRepeat_ResetCurrentCycle;(void)TighteningResult_PrintSummary;
    (void)TighteningResult_Sample;(void)LatestOriginal_FsmService;(void)MotorControl_SetIq;
    (void)argument;TickType_t wake=xTaskGetTickCount();MotorControl_SetIdle();
    UART_SendLiteral("PSI_IDENT_DIAGNOSTIC: manual point; no normal START; BEMF unchanged OFF\r\n");
    for (;;) {
        PsiIdentification *s=&psi_ident;
        if (tightening_start_request || tightening_stop_request) {
            uint8_t start=tightening_start_request;uint32_t req=tightening_start_request_id;
            tightening_start_request=tightening_stop_request=0U;
            if (s->active || s->queued) {
                ProtectedLoop_Stop();MotorControl_SetIdle();s->queued=s->active=0U;PsiIdent_Finish(s,0U);
            }
            if (start) Protocol_SendError(req,PROTO_ERR_BUSY,"PSI_USE_EXPLICIT_COMMAND");
        }
        if (s->active && cl_session.state!=CL_RUNNING) {
            s->active=0U;MotorControl_SetIdle();PsiIdent_Finish(s,0U);
        }
        if (s->queued) {
            if (!s->prepared) { s->encoder_before=cl_outer_n;s->prepared=1U; }
            else if (cl_outer_n!=s->encoder_before) {
                s->admitting=1U;uint8_t admitted=LatestOriginal_Admit();s->admitting=s->queued=0U;
                if (!admitted) { ProtectedLoop_Stop();PsiIdent_Finish(s,0U); }
            }
        }
        if (s->active) {
            uint32_t now=AS5047P_DmaNowUs();uint32_t elapsed=(uint32_t)(now-cl_session.start_us)/1000U;
            s->net_travel=encoder_position_deg-s->start_angle;
            uint8_t no_rotation=(uint8_t)(elapsed<PSI_DRIVE_MS &&
                TightenRundown_Update(&tightening_rundown,elapsed,(float)s->rpm,
                    encoder_speed_rpm,encoder_speed_detect_rpm,encoder_position_deg,foc_iq_ref_A,encoder_valid));
            if (no_rotation || fabsf(s->net_travel)>20000.0f) {
                ProtectedLoop_Stop();MotorControl_SetIdle();s->active=0U;PsiIdent_Finish(s,0U);
                FaultDiag_Capture(FOC_DIAG_PROCESS,no_rotation ? TIGHTEN_OUTCOME_NO_ROTATION : TIGHTEN_OUTCOME_ABORT,
                    FOC_TO_NONE,elapsed,no_rotation ? RUNDOWN_START_TIMEOUT_MS : 20000U);
            }
            if (s->active) PsiIdent_ObserveTask(now);
            if (s->active && (s->finished || elapsed>=PSI_DRIVE_MS)) {
                if (!s->finished) PsiIdent_Finish(s,1U);
                MotorControl_SetSpeed(0.0f); /* Original S-curve deceleration. */
                if (fabsf(encoder_speed_rpm)<=2.0f) s->stop_good_ms+=10U;else s->stop_good_ms=0U;
                if (s->stop_good_ms>=100U || elapsed>=PSI_STOP_MS) {
                    if (s->stop_good_ms<100U) s->passed=0U;
                    ProtectedLoop_Stop();s->active=0U;MotorControl_SetIdle();
                }
            }
        }
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(10U));
    }
}
