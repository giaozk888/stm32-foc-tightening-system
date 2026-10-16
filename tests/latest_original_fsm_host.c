/* Executes the actual adapter/protected binding. Register mocks, no board I/O. */
#define main previous_protected_cases
#include "protected_closed_loop_host.c"
#undef main
static struct { struct { uint32_t rundown_rpm; } params; } recipe_state;
#include "latest_original_fsm.inc"
static uint8_t protocol_esp_ping_uart_local,protocol_reply_route_active;
static uint8_t tightening_start_request_routed;
static uint16_t protocol_reply_route_dst,tightening_start_request_source_node;
static uint32_t tightening_start_request_id,last_error;
enum { PROTO_ERR_NOT_READY=1,PROTO_ERR_FW_STATE,PROTO_ERR_FAULT,PROTO_ERR_BUSY,PROTO_ERR_ROTOR_MOVING };
static uint32_t SystemPreflight_FailMask(void) { return 0U; }
static int BootHealth_IsCurrentTrial(void) { return trial; }
#define PREFLIGHT_FAIL_SPEED 1U
static int Protocol_SendFormatted(char *out,size_t size,const char *fmt,...)
{ (void)out; (void)size; (void)fmt; return 1; }
static void Protocol_SendError(uint32_t id,uint32_t code,const char *name)
{ (void)id; (void)name; last_error=code; }
#include "motor_job_port.inc"
static void setup(void)
{
    mock_tightening_busy=tightening_stop_request=0U;
    tightening_stop_request_id=0U;
    ready(); recipe_state.params.rundown_rpm=20U;
    protocol_esp_ping_uart_local=1U; protocol_reply_route_active=0U;
}
#ifndef LATEST_HOST_ENTRY
#define LATEST_HOST_ENTRY main
#endif
int LATEST_HOST_ENTRY(void)
{
#if defined(_WIN32)
    _set_error_mode(_OUT_TO_STDERR);
#endif
    char text[192];
    setup();
    ProtectedLoop_Command("MOTOR TEST PROFILE",text,sizeof text);
    assert(strstr(text,"NAME=LATEST_ORIGINAL_FSM HARD_OFF=0 ADAPT=1 FSM=ORIGINAL"));
    ProtectedLoop_Command("MOTOR TEST FILTER",text,sizeof text);
    assert(strstr(text,"ADAPT=1 HARD_OFF=0 DELAY_PAIRS=1"));
    ProtectedLoop_Command("MOTOR TEST ZERO ROBUST",text,sizeof text);
#if defined(FOC_LATEST_ZERO_COUNT_ONLY)
    assert(strstr(text,"MAX=OFF SEG_MAX=OFF") && strstr(text,"HARD_OFF=0"));
#else
    assert(strstr(text,"MAX=20 SEG_MAX=OFF") && strstr(text,"HARD_OFF=0"));
#endif
    ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
    assert(strstr(text,"USE_ORIGINAL_START")); off();
    assert(!cl_session.used && !cl_request);
    assert(LatestOriginal_Ready());
    assert(MotorJob_QueueStart(1U,1U,2U)==MOTOR_START_SAFE);
    protocol_esp_ping_uart_local=0U;
    MotorJob_HandleUartStart(1U); assert(last_error==PROTO_ERR_NOT_READY);
    protocol_esp_ping_uart_local=1U;
    MotorJob_HandleUartStart(2U);
    assert(tightening_start_request && tightening_start_request_id==2U);
    assert(!tightening_start_request_routed && !tightening_start_request_source_node);
    /* The original application acquires/clears the mailbox before admission. */
    tightening_start_request=0U;
    recipe_state.params.rundown_rpm=80U;
    assert(!LatestOriginal_Admit()); off(); assert(!cl_session.used);
    recipe_state.params.rundown_rpm=20U;
    foc_int_d_V=.75f; foc_int_q_V=-.75f;
    foc_vd_V=.8f; foc_vq_V=.8f;
    assert(LatestOriginal_Admit());
    assert(cl_session.state==CL_RUNNING && cl_session.used);
    assert(foc_int_d_V==0.0f && foc_int_q_V==0.0f && foc_vd_V==0.0f && foc_vq_V==0.0f);
    assert(gpio.ODR==DRIVER_SD_Pin && t1.CCER==0x555U);
    /* CONTACT_STOP is idle but busy; it must not end the original cycle. */
    mock_tightening_busy=1U; motor_control_mode=MOTOR_MODE_IDLE;
    LatestOriginal_FsmService(); assert(cl_session.state==CL_RUNNING);
    MotorControl_SetSpeed(17.0f);
    ProtectedLoop_TaskService();
    assert(motor_control_mode==MOTOR_MODE_SPEED && speed_request==17.0f);
    mock_tightening_busy=0U; LatestOriginal_FsmService();
    off(); assert(cl_session.state==CL_DONE && tightening_stop_request);
    assert(!LatestOriginal_Admit());
    setup(); assert(LatestOriginal_Admit());
    MotorJob_QueueStop(7U); off();
    assert(tightening_stop_request && tightening_stop_request_id==7U);
    /* Independent lease stops even when application FSM is still busy. */
    setup(); assert(LatestOriginal_Admit()); mock_tightening_busy=1U;
    while (cl_session.state==CL_RUNNING) {
        (void)pair(1551U,1551U);
        if (injected_seq_count%20U==0U) ProtectedLoop_TaskService();
    }
    off(); assert(cl_session.state==CL_DONE && tightening_stop_request && !foc_fault);
    assert(cl_stop_us-cl_session.start_us>=400000U && cl_stop_us-cl_session.start_us<=400025U);
    /* STOP/fault during planning must defeat admission, not be overwritten. */
    for (unsigned event=1U;event<=2U;++event) {
        setup(); prepare_interrupt=event;
        assert(!LatestOriginal_Admit()); off();
    }
    setup(); cl_session.outer_us=t2.CNT-2001U;
    assert(!LatestOriginal_Admit()); off();
    setup();
    assert(LatestOriginal_Admit()); mock_tightening_busy=1U;
    cl_session.outer_us=t2.CNT-2001U; tick(); off();
    assert(cl_flags & CL_OUTER_STALE);
    /* Same kernel repairs a single 25-count spike, not a two-point pulse. */
    FocCurrentMedian filter; uint16_t u=0U,v=0U;
    FocCurrentMedian_Begin(&filter);
    for (unsigned i=0U;i<80U;++i) (void)FocCurrentMedian_Push(&filter,1560U,1560U,&u,&v);
    const uint16_t input[]={1560U,1560U,1585U,1560U};
    for (unsigned i=0U;i<4U;++i) (void)FocCurrentMedian_Push(&filter,input[i],1560U,&u,&v);
    assert(u==1560U && v==1560U && filter.last_spike_mask==1U);
    puts("PASS latest backend / original FSM admission, no test-speed bypass, PI reset, pause, completion, lease, race and filter");
    return 0;
}
