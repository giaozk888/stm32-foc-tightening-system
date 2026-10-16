#define main original_binding_test_main
#include "protected_closed_loop_host.c"
#undef main
static void trace_ready(void)
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
    trace_ready(); char text[256];
    ProtectedLoop_Command("MOTOR TEST REPAIR",text,sizeof text); assert(strstr(text,"FROZEN=0"));
    /* Seven separated single repairs inside 32 feedback frames: actual
     * selector and actual protection, no synthetic repaired-mask injection. */
    for (unsigned i=0U;i<100U && !foc_fault;++i) {
        (void)pair(i%4U==2U?1800U:1551U,1551U);
    }
    assert(foc_fault && cl_safety.protection.reason==FOC_FP_REPAIR_BUDGET); off();
    assert(cl_safety.trace.frozen && cl_safety.trace.reason==FOC_FP_REPAIR_BUDGET);
    assert(cl_safety.trace.cause==1U && FocRepairTrace_Hits(cl_safety.trace.window)==7U);
    assert(cl_safety.trace.last_seq==cl_fault_seq && !cl_safety.trace.gap);
    assert(cl_safety.trace.streak==1U && cl_safety.trace.repaired==7U);
    FocRepairTraceRow last;
    assert(FocRepairTrace_Row(&cl_safety.trace,cl_safety.trace.count-1U,&last));
    assert(last.ready && last.mask==1U && last.filtered_u==1551U && last.filtered_v==1551U);
    assert(last.raw_u==1551U); /* Current raw != previous repaired center. */
    ProtectedLoop_Command("MOTOR TEST REPAIR",text,sizeof text);
    assert(strstr(text,"REASON=9 CAUSE=1 HITS=7 LIMIT=6 STREAK=1 SLIMIT=4 GAP=0"));
    puts(text);
    for (unsigned i=0U;i<32U;++i) {
        char cmd[40]; snprintf(cmd,sizeof cmd,"MOTOR TEST REPAIR ROW %u",i);
        ProtectedLoop_Command(cmd,text,sizeof text); puts(text);
    }
    FocRepairTrace saved=cl_safety.trace;
    for (unsigned i=0U;i<20U;++i) { (void)pair(1551U,1551U); tick(); }
    assert(!memcmp(&saved,&cl_safety.trace,sizeof saved)); off();
    ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text); assert(strstr(text,"REJECTED")); off();
    puts("PASS actual repair fault: 7-of-32 frozen, selector unchanged, gates off, immutable");
}
