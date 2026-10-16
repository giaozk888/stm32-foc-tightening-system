/* Execute the real original-FSM adapter and protected duty binding. */
#include "foc_adc_window.h"
static int rc_admission_ok = 1, rc_commit_ok = 1;
static int FocAdcTiming_RcActuationReady(void) { return rc_admission_ok; }
static int FocAdcTiming_CommitBeforeBottom(const FocWindowPlan *plan);
#define LATEST_HOST_ENTRY previous_latest_cases
#include "latest_original_fsm_host.c"
static int FocAdcTiming_CommitBeforeBottom(const FocWindowPlan *plan)
{
    assert(mask);
    if (!rc_commit_ok) return 0;
    FocAdcTiming_CommitPrepared(plan);
    return 1;
}
int main(void)
{
    char text[192];
    setup();
    ProtectedLoop_Command("MOTOR TEST PROFILE",text,sizeof text);
    assert(strstr(text,"NAME=RC_PROTECTED_CANDIDATE") && strstr(text,"FSM=ORIGINAL"));
    ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
    assert(strstr(text,"USE_ORIGINAL_START"));
    rc_admission_ok = 0;
    assert(!LatestOriginal_Ready() && !LatestOriginal_Admit());
    off(); assert(!cl_session.used);
    rc_admission_ok = 1;
    /* READY and disarmed/fault states do not build an unused duty plan. */
    unsigned idle_before = prepare_calls;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    assert(prepare_calls == idle_before);
    assert(LatestOriginal_Admit());
    unsigned before = prepared_commits;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    assert(prepared_commits == before + 1 && cl_session.state == CL_RUNNING);
    rc_commit_ok = 0;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    off();
    assert(cl_session.state == CL_FAULT && (cl_flags & CL_COMPUTE_LATE));
    assert(prepared_commits == before + 1 && cl_startup.first_flags == CL_COMPUTE_LATE);
    assert(!LatestOriginal_Admit()); /* Fault cannot be bypassed by START. */
    idle_before = prepare_calls;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    assert(prepare_calls == idle_before);
    rc_commit_ok = 1;
    setup(); assert(LatestOriginal_Admit());
    prepare_interrupt = 1;
    before = prepared_commits;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    off(); assert(prepared_commits == before && cl_session.state == CL_FAULT);
    setup(); assert(LatestOriginal_Admit());
    prepare_interrupt = 2;
    before = prepared_commits;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    off(); assert(prepared_commits == before && cl_session.state == CL_DONE);
    idle_before = prepare_calls;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    assert(prepare_calls == idle_before);
    setup(); assert(LatestOriginal_Admit());
    cl_armed = 0U;
    idle_before = prepare_calls;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    assert(prepare_calls == idle_before);
    setup(); assert(LatestOriginal_Admit());
    adc_fault = 1U;
    idle_before = prepare_calls;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    assert(prepare_calls == idle_before);
    setup(); assert(LatestOriginal_Admit());
    foc_fault = 1U;
    idle_before = prepare_calls;
    ProtectedLoop_SetDuty(.51f,.5f,.49f);
    assert(prepare_calls == idle_before);
    puts("PASS RC protected binding: original FSM, admission, commit fault, no retry, guard/STOP races");
    return 0;
}
