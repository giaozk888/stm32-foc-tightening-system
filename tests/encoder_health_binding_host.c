/* Exercise the actual protected binding, not a copied health predicate. */
#define main historic_binding_cases_not_run
#include "protected_closed_loop_host.c"
#undef main

int main(void)
{
    (void)historic_binding_cases_not_run;
    (void)MotorControl_SetSpeed; (void)Tightening_IsBusy;
    (void)UART_Async_IsReady; (void)FocAdcTiming_CommitPrepared; (void)UART_SendFormatted;
    ProtectedLoop_CurrentMonitor();
    reset();
    assert(ProtectedLoop_Init());
    assert(adc_priority==2U && guard_priority==3U);
    assert(ProtectedLoop_TimerHealthy());
    /* Exact encoder priority required: neither the old value nor any other
     * seemingly harmless lower priority is silently admitted. */
    for (unsigned i=0U;i<3U;++i) {
        for (unsigned p=0U;p<16U;++p) {
            encoder_priorities[i]=p;
            assert(!!ProtectedLoop_TimerHealthy()==(p==3U));
        }
        encoder_priorities[i]=3U;
    }
    for (unsigned p=0U;p<16U;++p) {
        adc_priority=p;
        assert(!!ProtectedLoop_TimerHealthy()==(p==2U));
    }
    adc_priority=2U;
    guard_priority=0U; assert(!ProtectedLoop_TimerHealthy()); guard_priority=3U;
    t7.ARR=25U; assert(!ProtectedLoop_TimerHealthy()); t7.ARR=24U;
    t2.PSC++; assert(!ProtectedLoop_TimerHealthy()); t2.PSC--;
    enabled=0U; assert(!ProtectedLoop_TimerHealthy()); enabled=1U;
    assert(ProtectedLoop_TimerHealthy());
    /* Existing guard still closes output and latches BAD_TIMER on drift. */
    encoder_priorities[0]=1U;
    tick(); off();
    assert(cl_flags&CL_BAD_TIMER);
    puts("PASS encoder health: exact priorities accepted, drift rejected, output off");
    return 0;
}
