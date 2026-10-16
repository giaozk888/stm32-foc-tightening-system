/* Actual hard-off binding with register faults, reference and compact builds.
 * RUNNING is manually injected into mocks only to exercise unchanged checks;
 * the real adaptive profile has no bridge-enable admission path. */
#define main original_binding_test_main
#include "protected_closed_loop_host.c"
#undef main
static void shadow_ready(void)
{
    reset(); assert(ProtectedLoop_Init());
    for (unsigned i=0U;i<100U;++i) (void)pair(1551U,1551U);
    ProtectedLoop_TaskService(); ProtectedLoop_TaskService();
    assert(cl_session.state==CL_READY && !foc_fault); off();
}
int main(void)
{
    (void)MotorControl_SetSpeed; (void)FocAdcTiming_Prepare;
    (void)FocAdcTiming_CommitPrepared; (void)FocAdcTiming_PlanFailed;
    (void)UART_Async_IsReady; (void)Tightening_IsBusy;
    for (unsigned n=0U;n<29U;++n) {
        shadow_ready();
        /* Simulated running-state checks, never a real actuation command. */
        if (n>=23U && n<=27U) {
            cl_session.state=CL_RUNNING; cl_session.start_us=t2.CNT;
            cl_session.outer_us=t2.CNT; cl_boot_confirmed=1U;
            gpio.ODR=DRIVER_SD_Pin; t1.BDTR|=TIM_BDTR_MOE; t1.CCER=0x555U;
        }
        switch(n) {
        case 0: break;
        case 1: clock_regs.APB1ENR1=0U; break;
        case 2: t2.CR1=0U; break;
        case 3: ++t2.PSC; break;
        case 4: --t2.ARR; break;
        case 5: ++t7.PSC; break;
        case 6: ++t7.ARR; break;
        case 7: t7.DIER=0U; break;
        case 8: t7.CR1=0U; break;
        case 9: guard_priority=1U; break;
        case 10: adc_priority=1U; break;
        case 11: encoder_priorities[0]=3U; break;
        case 12: encoder_priorities[1]=3U; break;
        case 13: encoder_priorities[2]=3U; break;
        case 14: enabled=0U; break;
        case 15: adc_fault=1U; break;
        case 16: encoder_valid=0U; break;
        case 17: encoder_theta_e_pred=NAN; break;
        case 18: planner_ok=0U; break;
        case 19: gpio.ODR=DRIVER_SD_Pin; break;
        case 20: t1.BDTR|=TIM_BDTR_AOE; break;
        case 21: t1.CR1&=~TIM_CR1_CEN; break;
        case 22: cl_last_us=t2.CNT-101U; break;
        case 23: encoder_speed_rpm=NAN; break;
        case 24: cl_session.outer_us=t2.CNT-2001U; break;
        case 25: fw_update.active=1U; break;
        case 26: cl_boot_confirmed=0U; break;
        case 27: run_zero_cal_done=0U; break;
        case 28: ProtectedLoop_WorkEnd(t2.CNT-50U); break;
        }
        tick();
        if (n==0U) assert(!foc_fault);
        else { assert(foc_fault && cl_fault_valid); off(); }
        printf("%u:%u:%lu:%lu\n",n,foc_fault,(unsigned long)cl_flags,
            (unsigned long)cl_safety.protection.fault_flags);
    }
    shadow_ready(); char text[192];
#if defined(FOC_IRQ_COMPACT)
    ProtectedLoop_Command("MOTOR TEST COMPACT",text,sizeof text);
    assert(strstr(text,"FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50"));
#endif
    ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
    assert(strstr(text,"REJECTED")); off();
    puts("PASS 29 guardian cases; hard-off admission retained");
}
