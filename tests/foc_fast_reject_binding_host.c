#define main legacy_binding_cases_not_run
#include "protected_closed_loop_host.c"
#undef main
static struct { struct { uint32_t rundown_rpm; } params; } recipe_state;
#include "latest_original_fsm.inc"
static void init(void)
{
    (void)MotorControl_SetSpeed; /* Original task helper unused by this adapter. */
    (void)FocAdcTiming_Prepare; (void)FocAdcTiming_CommitPrepared;
    (void)FocAdcTiming_PlanFailed; (void)UART_Async_IsReady; (void)LatestOriginal_Ready;
    reset(); cl_current_cycles=(FocCurrentCycleStats){0};
    assert(ProtectedLoop_Init());
    for (unsigned i=0;i<10U;++i) assert(pair(1551U,1551U));
    ProtectedLoop_TaskService(); ProtectedLoop_TaskService();
    recipe_state.params.rundown_rpm=20U;
    LatestOriginal_FsmService();
    assert(!mask && cl_session.state==CL_READY && !foc_fault);
}
int main(void)
{
    char status[192];
    init();
    ProtectedLoop_Command("MOTOR TEST FILTER",status,sizeof status);
    assert(strstr(status,"REPAIR=0") && strstr(status,"UNRESOLVED_LIMIT=3") && strstr(status,"METHOD=TWO_SAMPLE"));
    ProtectedLoop_Command("MOTOR TEST PROTECTION",status,sizeof status);
    assert(strstr(status,"RAW_CONFIRM_4"));
    ProtectedLoop_CurrentMonitor();
    assert(strstr(validation_log,"CURRENT VALIDATION") && strstr(validation_log,"deadline_miss=0"));
    FocCurrentValidation saved=cl_safety.validation;
    cl_safety.validation=(FocCurrentValidation){
        .current_samples_total=UINT32_MAX,.current_suspect_total=UINT32_MAX,
        .current_confirmed_spike=UINT32_MAX,.current_confirmed_transition=UINT32_MAX,
        .current_unresolved_total=UINT32_MAX,.current_unresolved_consecutive=UINT32_MAX,
        .current_unresolved_max_consecutive=UINT32_MAX,.current_measurement_fault_count=UINT32_MAX,
        .current_recovered_after_unresolved=UINT32_MAX };
    cl_current_cycles=(FocCurrentCycleStats){.max_cycles=UINT32_MAX,
        .last_cycles=UINT32_MAX,.normal_max_cycles=UINT32_MAX,
        .suspect_max_cycles=UINT32_MAX,.unresolved_max_cycles=UINT32_MAX,
        .deadline_miss_count=UINT32_MAX};
    ProtectedLoop_CurrentMonitor();
    assert(strstr(validation_log,"spike=4294967295") && strstr(validation_log,"unresolved=4294967295") &&
        strstr(validation_log,"deadline_miss=4294967295\r\n"));
    cl_safety.validation=saved; cl_current_cycles=(FocCurrentCycleStats){0};
    encoder_theta_e_pred=TWO_PI_F-.0001f; encoder_omega_e_rad_s=10.0f;
    ProtectedLoop_AdvanceAngle(); assert(encoder_theta_e_pred>=0 && encoder_theta_e_pred<.001f);
    encoder_theta_e_pred=0; encoder_omega_e_rad_s=-10.0f;
    ProtectedLoop_AdvanceAngle(); assert(encoder_theta_e_pred<TWO_PI_F && encoder_theta_e_pred>6.0f);
#if defined(FOC_FAST_REJECT_COMPUTE_ONLY)
    assert(!ProtectedLoop_Ready() && !LatestOriginal_Admit());
    cl_session.state=CL_RUNNING; cl_request=1U;
    ProtectedLoop_TaskService(); off(); assert(!cl_armed && foc_fault);
    ProtectedLoop_SetDuty(.4f,.6f,.5f); off(); assert(!prepared_commits);
#else
    assert(ProtectedLoop_Ready() && LatestOriginal_Ready() && LatestOriginal_Admit());
    assert(cl_session.state==CL_RUNNING && t1.CCER==0x555U);
    foc_int_d_V=.25f; foc_int_q_V=-.25f;
    assert(!pair(1650,1551) && cl_armed && cl_current_path==2U);
    assert(foc_int_d_V==.25f && foc_int_q_V==-.25f && t1.CCER==0x555U);
    assert(pair(1551,1551) && cl_safety.validation.current_confirmed_spike==1U);
    assert(!pair(1650,1551) && pair(1651,1551)); /* persistent transition */
    assert(cl_safety.validation.current_confirmed_transition==1U && !foc_fault);
    assert(!pair(1850,1551) && !pair(1400,1551) && !pair(1900,1551) && !pair(1300,1551));
    off(); assert(!cl_armed && foc_fault && cl_safety.protection.reason==FOC_FP_CURRENT_INVALID);
    init(); assert(LatestOriginal_Admit());
    assert(!pair(900,1551) && cl_armed);
    for (unsigned i=1U;i<CUR_CONFIRM_MAX_CYCLES;++i) assert(pair(900,1551) && cl_armed);
    assert(!pair(900,1551)); off();
    assert(cl_safety.protection.reason==FOC_FP_TIMEOUT);
    assert(cl_safety.protection.timeout.reason==FOC_TO_CURRENT_CONFIRM);
#endif
    init(); cl_current_path=2U; mock_dwt.CYCCNT=UINT32_MAX-20U;
    uint32_t start=mock_dwt.CYCCNT; mock_dwt.CYCCNT+=8500U;
    ProtectedLoop_AdcProfileEnd(start); off();
    assert(cl_current_cycles.deadline_miss_count==1U && (cl_flags&CL_COMPUTE_LATE));
    init(); encoder_omega_e_rad_s=INFINITY;
    ProtectedLoop_AdvanceAngle(); off(); assert(cl_flags&CL_BAD_ENCODER);
    puts("PASS actual binding: raw OC/invalid shuts gates, stats/profile wrap, original admission or compute-only denial");
    return 0;
}
