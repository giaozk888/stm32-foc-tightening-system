/* Real protected binding against register/task mocks; never touches a board. */
#include <string.h>
static char zero_report[512];
static void UART_SendLiteral(const char *s)
{
    strncat(zero_report,s,sizeof(zero_report)-strlen(zero_report)-1U);
}
#define main previous_binding_cases
#include "protected_closed_loop_host.c"
#undef main
int main(void)
{
    (void)MotorControl_SetSpeed; (void)UART_SendFormatted;
    (void)FocAdcTiming_CommitPrepared;
    ProtectedLoop_CurrentMonitor();
    reset();
    assert(ProtectedLoop_Init());
    assert(cl_session.state==CL_READY && cl_zero.count==4000U);
    assert(strstr(zero_report,"ZERO CAL valid=4000 reject=0 total=4000"));
    assert(strstr(zero_report,"zero_u=1551 zero_v=1551 result=1 STATE=3"));
    char out[256];
    ProtectedLoop_Command("MOTOR TEST ZERO",out,sizeof out);
    assert(strstr(out,"valid=4000 reject=0 total=4000"));
    off();
    /* Re-enter only the mocked calibration to exercise actual fault ownership. */
    cl_session.state=CL_CALIBRATING;
    FocZeroMedian_Begin(&cl_zero_filter,&cl_zero,1561U);
    for (unsigned i=0;i<FOC_ZERO_SETTLE_PAIRS;++i) (void)pair(1561U,1561U);
    for (unsigned i=0;i<3U;++i) (void)pair(1561U,1561U);
    for (unsigned i=0;i<3U;++i) (void)pair(1700U,1561U);
    for (unsigned i=0;i<4U;++i) (void)pair(1561U,1561U);
    assert(cl_zero.state==FOC_ZERO_FAILED && cl_session.state==CL_FAULT);
    assert(cl_flags&CL_BAD_ZERO);
    off();
    puts("PASS zero admission protected binding");
    return 0;
}
