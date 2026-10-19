/* Task-only owner. No CCR/MOE/SD writes. Existing admission/ADC protection and
 * independent TIM7 lease own hardware. No calibration/fault bypass. */
#if defined(FOC_SPEED_DYNAMIC_DIAG)
/* Reuse the protected one-shot owner, NOT the fixed-Iq control mode. */
__attribute__((optimize("Os")))
static int TorqueChain_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST SPEED500",sizeof("MOTOR TEST SPEED500")-1U)) return 0;
    if (!strcmp(cmd,"MOTOR TEST SPEED500 STATUS")) {
        snprintf(out,size,"OK SPEED500 RPM=20 IQ_LIMIT_MA=500 DYNAMIC_IQ=1 LEASE_US=5000000 USED=%u ACTIVE=%u DENIED=%u",
            torque_diag.used,torque_diag.active,torque_diag.denied);
        return 1;
    }
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint8_t ready=(uint8_t)(cl_session.state==CL_READY && !cl_session.used &&
        ProtectedLoop_Ready() && motor_control_mode==MOTOR_MODE_IDLE &&
        !Tightening_IsBusy() && !tightening_start_request && !tightening_stop_request);
    int accepted=FocTorqueChain_Queue(&torque_diag,cmd,ready);
    __set_PRIMASK(mask);
    snprintf(out,size,accepted ? "OK SPEED500 QUEUED MANUAL_ONE_SHOT=1" : "ERR 109 SPEED500_DENIED");
    return 1;
}
#elif defined(FOC_BREAKAWAY_CURRENT_TEST)
static volatile uint32_t breakaway_capture_tag=BREAKAWAY_CAPTURE_TAG;
static volatile const uint16_t breakaway_direct_limit_ma=(uint16_t)(MOTOR_DIRECT_IQ_LIMIT_A*1000.0f+0.5f);
__attribute__((optimize("Os")))
static int TorqueChain_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST BREAKAWAY",20U)) return 0;
    uint16_t limit_ma=breakaway_direct_limit_ma;
    if (!strcmp(cmd,"MOTOR TEST BREAKAWAY STATUS")) {
        snprintf(out,size,"OK BREAKAWAY IQ_MA=%u LIMIT_MA=%u ID_MA=0 LEASE_US=%lu PERIOD_US=%lu USED=%u ACTIVE=%u SIGN=%ld TAG=%08lX",
            torque_diag.iq_mA,limit_ma,(unsigned long)BREAKAWAY_TEST_DURATION_US,
            (unsigned long)BREAKAWAY_RECORD_PERIOD_US,torque_diag.used,torque_diag.active,
            (long)torque_diag.sign,(unsigned long)breakaway_capture_tag);
        return 1;
    }
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint8_t ready=(uint8_t)(cl_session.state==CL_READY && !cl_session.used &&
        ProtectedLoop_Ready() && motor_control_mode==MOTOR_MODE_IDLE &&
        !Tightening_IsBusy() && !tightening_start_request && !tightening_stop_request);
    int accepted=FocBreakaway_Queue(&torque_diag,cmd,ready,limit_ma);
    __set_PRIMASK(mask);
    snprintf(out,size,accepted==1 ? "OK BREAKAWAY QUEUED MANUAL_ONE_SHOT=1" :
        accepted==-2 ? "ERR 109 LIMIT_BLOCKED" : "ERR 109 BREAKAWAY_DENIED");
    return 1;
}
#else
__attribute__((optimize("Os")))
static int TorqueChain_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST TORQUE",17U)) return 0;
    if (!strcmp(cmd,"MOTOR TEST TORQUE STATUS")) {
        snprintf(out,size,"OK TORQUE IQ_MA=" FOC_TORQUE_CHAIN_IQ_TEXT " ID_MA=0 LEASE_US=200000 PERIOD_US=8000 USED=%u ACTIVE=%u DENIED=%u SIGN=%ld OFFSET_DEG=%ld",
            torque_diag.used,torque_diag.active,torque_diag.denied,
            (long)torque_diag.sign,(long)torque_diag.offset_deg);
        return 1;
    }
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint8_t ready=(uint8_t)(cl_session.state==CL_READY && !cl_session.used &&
        ProtectedLoop_Ready() && motor_control_mode==MOTOR_MODE_IDLE &&
        !Tightening_IsBusy() && !tightening_start_request && !tightening_stop_request);
    int accepted=FocTorqueChain_Queue(&torque_diag,cmd,ready);
    __set_PRIMASK(mask);
    snprintf(out,size,accepted ? "OK TORQUE QUEUED MANUAL_ONE_SHOT=1" : "ERR 109 TORQUE_DENIED");
    return 1;
}
#endif
__attribute__((optimize("Os")))
static void TorqueChain_Service(void)
{
    /* Only task state here. Do not mask ADC during the original preemptible
     * PWM planning. LatestOriginal_Admit rechecks all gates under its own
     * existing bounded transaction, including pending STOP/START above. */
    if (tightening_stop_request || tightening_start_request) {
        if (torque_diag.active) ProtectedLoop_Stop();
        if (torque_diag.queued) torque_diag.denied=1U;
        torque_diag.queued=torque_diag.active=0U;
    }
    if (torque_diag.active && cl_session.state!=CL_RUNNING) {
        torque_diag.active=0U; MotorControl_SetIdle();
    }
    if (torque_diag.queued) {
        if (cl_session.state!=CL_READY || adc_fault || foc_fault || Tightening_IsBusy()) {
            torque_diag.queued=0U; torque_diag.denied=1U;
        } else if (!torque_diag.prepared) {
            /* Offset selected while gates OFF. Wait for fresh accepted angle. */
            torque_diag.encoder_before=cl_outer_n;
            torque_diag.prepared=1U;
        } else if (cl_outer_n!=torque_diag.encoder_before) {
            torque_diag.admitting=1U;
            if (!LatestOriginal_Admit()) torque_diag.denied=1U;
            torque_diag.admitting=0U; torque_diag.queued=0U;
        }
    }
}
