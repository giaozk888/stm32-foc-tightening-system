/* Actual protected binding in register mocks; no board/serial I/O. */
#define main original_protected_cases
#include "protected_closed_loop_host.c"
#undef main
int main(void)
{
    char text[192];
    ready();
    ProtectedLoop_Command("MOTOR TEST PROFILE",text,sizeof text);
    assert(strstr(text,"NAME=COMPACT_CLOSED_LOOP HARD_OFF=0 ADAPT=0 ZERO=BOUNDED"));
    assert(strstr(text,"LOCAL=1 RPM=20 LEASE_US=400000 QUALIFIED=0"));
    ProtectedLoop_Command("MOTOR TEST RAM",text,sizeof text);
    assert(strstr(text,"HARD_OFF=0 DEADLINE_US=50"));
    ProtectedLoop_Command("MOTOR TEST COMPACT",text,sizeof text);
    assert(strstr(text,"HARD_OFF=0 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50"));
    off(); /* Reading identity cannot queue/enable. */
    assert(!cl_session.used && !cl_session.queued && !cl_request);
    /* Break may occur despite PRIMASK: running gates must be refreshed both
     * before Push and after the timestamp at Take. Never reuse hard-off proof. */
    for (unsigned instant=1U;instant<=2U;++instant) {
        run(); break_on_time_call=instant;
        t2.CNT+=50U; ++injected_seq_count;
        assert(!ProtectedLoop_Pair(1551U,1551U));
        off(); assert(foc_fault && cl_session.state==CL_FAULT);
    }
    reset(); analog_vdda_boot_valid=0U;
    assert(!ProtectedLoop_Init()); off();
    assert(!cl_armed && !cl_session.used);
    puts("PASS compact closed-loop identity, break timing and invalid-zero admission");
    return 0;
}
