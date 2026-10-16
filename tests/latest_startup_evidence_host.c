#define LATEST_HOST_ENTRY previous_latest_cases
#include "latest_original_fsm_host.c"
int main(void)
{
    char text[256];
    memset(&cl_startup,0,sizeof cl_startup);
    setup(); assert(LatestOriginal_Admit());
    mock_tightening_busy=1U;
    ProtectedLoop_Command("MOTOR TEST STARTUP",text,sizeof text);
    assert(strstr(text,"NOT_FROZEN"));
    ProtectedLoop_Command("MOTOR TEST STARTUP CONFIG",text,sizeof text);
    assert(strstr(text,"ROWS=32 FIRST_CAUSE=1"));
    encoder_ok=1U; speed_ref_rpm=.2f;
    ProtectedLoop_TaskService();
    assert(cl_startup.total==1U && cl_startup.rows[0].ref==.2f);
    speed_ref_rpm=5.8f; encoder_rpm_instant=100.0f; encoder_speed_rpm=60.7f;
    foc_iq_ref_A=-.1f; foc_iq_A=.2f;
    encoder_ok=3U; /* Real outer-update mock preempted by independent guard. */
    ProtectedLoop_TaskService();
    off();
    assert(cl_flags==CL_OVERSPEED && cl_startup.first_flags==CL_OVERSPEED);
    assert(cl_startup.fault.iq_ref==-.1f && !foc_iq_ref_A);
    ProtectedLoop_EmergencyOff(CL_BAD_ENCODER);
    assert(cl_flags==(CL_OVERSPEED|CL_BAD_ENCODER));
    assert(cl_startup.first_flags==CL_OVERSPEED);
    ProtectedLoop_Command("MOTOR TEST STARTUP",text,sizeof text);
    assert(strstr(text,"FIRST_FLAGS=1024"));
    ProtectedLoop_Command("MOTOR TEST STARTUP FAULT",text,sizeof text);
    assert(strstr(text,"RPM10=58,1000,607") && strstr(text,"MA=-100,0,200"));
    ProtectedLoop_Command("MOTOR TEST STARTUP FRAME 1",text,sizeof text);
    assert(strstr(text,"ERR"));
    const char *invalid[]={"MOTOR TEST STARTUP FRAME -1","MOTOR TEST STARTUP FRAME 32",
        "MOTOR TEST STARTUP FRAME 99999999999999999999999999",
        "MOTOR TEST STARTUP FRAME 0 junk","MOTOR TEST STARTUP FRAME "};
    for (unsigned i=0;i<sizeof invalid/sizeof invalid[0];++i) {
        ProtectedLoop_Command(invalid[i],text,sizeof text); assert(strstr(text,"ERR"));
    }
    /* Exercise production readback of an immutable row (no live reads). */
    cl_startup.rows[0]=(FocStartupFrame){.us=123U,.iq_ref=-.1f};
    cl_startup.total=1U;
    ProtectedLoop_Command("MOTOR TEST STARTUP FRAME 0",text,sizeof text);
    assert(strstr(text,"US=123") && strstr(text,"MA=-100,0,0"));
    /* A genuine encoder error still closes outputs and retains its flag. */
    memset(&cl_startup,0,sizeof cl_startup);
    setup(); encoder_ok=1U; encoder_speed_rpm=0.0f;
    assert(LatestOriginal_Admit()); encoder_ok=0U;
    ProtectedLoop_TaskService(); off();
    assert(cl_flags==CL_BAD_ENCODER && cl_startup.first_flags==CL_BAD_ENCODER);
    memset(&cl_startup,0,sizeof cl_startup);
    setup(); encoder_ok=1U; assert(LatestOriginal_Admit());
    ProtectedLoop_Stop();
    assert(cl_startup.frozen && !cl_startup.fault_valid);
    puts("PASS actual binding: first cause, no secondary encoder mislabel, real encoder error still trips");
    return 0;
}
