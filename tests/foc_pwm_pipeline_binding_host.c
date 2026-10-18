/* Actual protected binding; register commit separately tested in its adapter. */
#define main old_binding_main_not_run
#include "protected_closed_loop_host.c"
#undef main
static void setup(void)
{
    (void)MotorControl_SetSpeed; (void)Tightening_IsBusy;
    (void)UART_Async_IsReady; (void)FocAdcTiming_CommitPrepared; (void)UART_SendFormatted;
    ProtectedLoop_CurrentMonitor();
    reset(); pending_commits=0U;
    assert(ProtectedLoop_Init() && cl_session.state==CL_READY);
    assert(guard_priority==3U && adc_priority==2U);
    assert(!cl_pwm_pending.valid && cl_pwm_pending.ccr[0]==2124U);
}
static int frame(uint16_t u,uint16_t v)
{
    ProtectedLoop_PwmEntry(); /* Before this pair is read/validated. */
    int accepted=pair(u,v);
    if (accepted) ProtectedLoop_SetDuty(.52f,.5f,.48f);
    return accepted;
}
int main(void)
{
    setup(); pipeline_guard_probe=1U; tick();
    assert(cl_armed && !cl_flags);
    pipeline_adc_preempt=1U; tick(); /* Fresh ADC timestamp > old health-now. */
    pipeline_guard_probe=0U;
    assert(!pipeline_adc_preempt && cl_armed && !cl_flags && !mask);
    setup();
    assert(frame(1551U,1551U));
    assert(!pending_commits && cl_pwm_pending.valid);
    uint16_t expected[3]; memcpy(expected,cl_pwm_pending.ccr,sizeof expected);
    assert(frame(1551U,1551U) && pending_commits==1U);
    assert(!memcmp(committed_phase,expected,sizeof expected));
    ProtectedLoop_SetDuty(.48f,.50f,.52f); /* A different result of this frame. */
    assert(!memcmp(committed_phase,expected,sizeof expected)); /* Not committed at tail. */
    memcpy(expected,cl_pwm_pending.ccr,sizeof expected);
    foc_int_d_V=.4f; foc_int_q_V=-.3f;
    assert(!frame(1700U,1551U));
    assert(cl_current_path==FOC_CURRENT_PATH_SUSPECT && cl_pwm_pending.valid);
    assert(foc_int_d_V==.4f && foc_int_q_V==-.3f);
    assert(!memcmp(cl_pwm_pending.ccr,expected,sizeof expected));
    assert(frame(1551U,1551U)); /* Same held command committed again. */
    assert(!memcmp(committed_phase,expected,sizeof expected));
    uint32_t writes=pending_commits;
    motor_control_mode=MOTOR_MODE_SPEED;
    ProtectedLoop_PwmEntry();
    assert(!cl_pwm_pending.valid && pending_commits==writes);
    /* Even an away-and-back mode change must clear the slot explicitly. */
    cl_pwm_pending.valid=1U; ProtectedLoop_PwmInvalidate();
    assert(!cl_pwm_pending.valid);
    setup(); assert(frame(1551U,1551U));
    ProtectedLoop_EmergencyOff(CL_BAD_ENCODER);
    writes=pending_commits; ProtectedLoop_PwmEntry();
    assert(!cl_pwm_pending.valid && pending_commits==writes && !cl_armed);
    off();
    setup(); assert(frame(1551U,1551U));
    ProtectedLoop_Stop(); ProtectedLoop_PwmEntry();
    assert(!cl_pwm_pending.valid && !pending_commits);
    puts("PASS pipeline actual binding startup / next-cycle / invalid hold / mode / fault / stop");
}
