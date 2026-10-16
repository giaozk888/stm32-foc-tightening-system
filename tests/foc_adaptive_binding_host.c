#define main original_binding_test_main
#include "protected_closed_loop_host.c"
#undef main
int main(void)
{
    /* These mocks are deliberately unused by the hard-off build. */
    (void)MotorControl_SetSpeed; (void)FocAdcTiming_Prepare;
    (void)FocAdcTiming_CommitPrepared; (void)FocAdcTiming_PlanFailed;
    (void)UART_Async_IsReady; (void)Tightening_IsBusy;
    char text[192]; reset(); assert(ProtectedLoop_Init()); off();
    for (unsigned i=0U;i<100U;++i) (void)pair(1551U,1551U);
    ProtectedLoop_TaskService(); ProtectedLoop_TaskService(); off();
    assert(cl_session.state==CL_READY && !foc_fault && !ProtectedLoop_Ready());
    ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
    assert(strstr(text,"REJECTED") && !cl_request); off();
    ProtectedLoop_Command("MOTOR TEST FILTER",text,sizeof text);
    assert(strstr(text,"ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1") && strlen(text)<180U);
#if defined(FOC_ZERO_ALL_REJECTED_DIAG)
    ProtectedLoop_Command("MOTOR TEST ZERO POLICY",text,sizeof text);
    assert(strstr(text,"DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V"));
#endif
    ProtectedLoop_Command("MOTOR TEST ZERO ROBUST",text,sizeof text);
    assert(strstr(text,"SEGMENTS=8 OUTLIERS=0") && strlen(text)<180U);
    assert(strstr(text,"SEG_MAX=OFF SEG_OUTLIERS=0 FLAGS=0 HARD_OFF=1"));
#if defined(FOC_ZERO_TOTAL_BUDGET_OFF)
    assert(strstr(text,"MAX=OFF SEG_MAX=OFF"));
#else
    assert(strstr(text,"MAX=20 SEG_MAX=OFF"));
#endif
    assert(TIM1->CR1&TIM_CR1_CEN);
    ProtectedLoop_SetDuty(0.9f,0.1f,0.5f); off(); assert(!prepared_commits);
    /* Hard-off computation must retain the ADC-only trigger across duties.
     * Otherwise the next guardian tick reports BAD_TIMER after one FOC step. */
    assert(TIM1->CR1&TIM_CR1_CEN);
    for (unsigned i=0U;i<1000U;++i) {
        assert(pair(1551U,1551U));
        ProtectedLoop_SetDuty(0.95f,0.05f,0.5f);
        ProtectedLoop_TaskService(); off();
        assert(!foc_fault && (TIM1->CR1&TIM_CR1_CEN));
    }
    cl_request=1U; ProtectedLoop_TaskService(); off();
    assert(cl_flags&CL_BAD_ADMISSION);
    assert(!(TIM1->CR1&TIM_CR1_CEN));
    ProtectedLoop_SetDuty(0.9f,0.1f,0.5f); off();
    assert(!(TIM1->CR1&TIM_CR1_CEN)); /* A late duty cannot restart sampling. */
    reset(); assert(ProtectedLoop_Init()); off();
    for (unsigned i=0U;i<10U;++i) (void)pair(1551U,1551U);
    tick(); tick(); tick(); tick(); tick(); off(); assert(foc_fault);
    puts("PASS actual adaptive binding: zero, START denied, duty locked, stale request and timeout off");
    return 0;
}
