/* Executes actual binding + original FSM admission against register mocks. */
#define main previous_binding_cases
#include "protected_closed_loop_host.c"
#undef main
#include "tighten_params.h"
static struct { TightenParams_t params; } recipe_state;
#include "latest_original_fsm.inc"

static void setup(void)
{
    (void)MotorControl_SetSpeed; (void)UART_SendFormatted;
    (void)FocAdcTiming_CommitPrepared;
    ProtectedLoop_CurrentMonitor();
    reset(); pending_commits=0U; pipeline_plan_matches=pipeline_timing_ready=1U;
    mock_tightening_busy=tightening_stop_request=0U;
    assert(ProtectedLoop_Init() && cl_session.state==CL_READY);
    recipe_state.params=(TightenParams_t)TIGHTEN_PARAMS_DEFAULT_INITIALIZER;
    recipe_state.params.rundown_rpm=20U;
    ProtectedLoop_TaskService(); ProtectedLoop_TaskService();
    assert(periodic && !ProtectedLoop_Ready());
    for (unsigned i=0U;i<1000U;++i) {
        ProtectedLoop_PwmEntry();
        assert(pair(1551U,1551U));
        ProtectedLoop_SetDuty(.52f,.5f,.48f);
        if (i%20U==0U) ProtectedLoop_TaskService();
        assert(!cl_pwm_pending.valid); /* READY can never stage nonneutral. */
        assert(committed_phase[0]==2125U && committed_phase[1]==2125U &&
               committed_phase[2]==2125U);
        off();
    }
    assert(ProtectedLoop_Ready() && !cl_session.used && !prepared_commits);
}
static int frame(uint16_t u,uint16_t v)
{
    ProtectedLoop_PwmEntry();
    int accepted=pair(u,v);
    if (accepted) ProtectedLoop_SetDuty(.52f,.5f,.48f);
    return accepted;
}
static void start(void)
{
    assert(LatestOriginal_Admit());
    assert(!cl_pwm_pending.valid && !prepared_commits);
    assert(cl_session.state==CL_RUNNING && gpio.ODR==DRIVER_SD_Pin);
    mock_tightening_busy=1U;
    MotorControl_SetSpeed(20.0f);
}
int main(int argc,char **argv)
{
    unsigned which=argc==2 ? (unsigned)strtoul(argv[1],NULL,10) : 0U;
    setup();
    if (which==1U) { pipeline_timing_ready=0U; assert(!LatestOriginal_Admit()); off(); }
    else if (which==2U) { trial=1U; cl_boot_confirmed=0U; assert(!LatestOriginal_Admit()); off(); }
    else if (which==14U) { prepare_interrupt=1U; assert(!LatestOriginal_Admit()); off(); }
    else if (which==15U) { prepare_interrupt=2U; assert(!LatestOriginal_Admit()); off(); }
    else if (which==16U) { cl_pwm_neutral_commits=999U; assert(!LatestOriginal_Admit()); off(); }
    else if (which==17U) { cl_late=1U; assert(!LatestOriginal_Admit()); off(); }
    else if (which==18U) { cl_current_cycles.deadline_miss_count=1U; assert(!LatestOriginal_Admit()); off(); }
    else if (which==19U) {
        pipeline_plan_matches=0U; ProtectedLoop_SetDuty(.52f,.5f,.48f);
        off(); assert(cl_flags&CL_BAD_ADC); assert(!LatestOriginal_Admit());
    }
#if defined(FOC_LOADED_FSM_TRIAL)
    else if (which==20U) {
        assert(CL_MAX_US==12000000U); start();
        assert(!ClSession_Expired(&cl_session,cl_session.start_us+400001U));
        assert(!ClSession_Expired(&cl_session,cl_session.start_us+11999999U));
        assert(ClSession_Expired(&cl_session,cl_session.start_us+12000000U));
        ProtectedLoop_Stop(); off(); assert(!LatestOriginal_Admit());
    } else if (which==21U) {
        recipe_state.params.rundown_timeout_ms=8001U;
        assert(!LatestOriginal_Admit()); off();
    } else if (which==22U) {
        recipe_state.params.hold_ms=501U;
        assert(!LatestOriginal_Admit()); off();
    } else if (which==23U) {
        start(); mock_tightening_busy=0U; LatestOriginal_FsmService();
        off(); assert(cl_session.state==CL_DONE && !LatestOriginal_Admit());
    } else if (which==24U) {
        recipe_state.params.rundown_rpm=21U;
        assert(!LatestOriginal_Admit()); off();
    }
#endif
    else {
        start();
        uint32_t writes=pending_commits;
        assert(frame(1551U,1551U) && pending_commits==writes && cl_pwm_pending.valid);
        uint16_t expected[3]; memcpy(expected,cl_pwm_pending.ccr,sizeof expected);
        assert(frame(1551U,1551U) && pending_commits==writes+1U);
        assert(!memcmp(expected,committed_phase,sizeof expected));
        if (which==3U) {
            foc_int_d_V=.4f; foc_int_q_V=-.3f;
            assert(!frame(1700U,1551U));
            assert(cl_current_path==FOC_CURRENT_PATH_SUSPECT);
            assert(foc_int_d_V==.4f && foc_int_q_V==-.3f && cl_pwm_pending.valid);
            assert(!memcmp(expected,cl_pwm_pending.ccr,sizeof expected));
            assert(frame(1551U,1551U));
        } else if (which==4U) {
            ProtectedLoop_Stop(); off(); writes=pending_commits;
            ProtectedLoop_PwmEntry(); assert(!cl_pwm_pending.valid && pending_commits==writes);
            assert(!LatestOriginal_Admit());
        } else if (which==5U) {
            ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); off(); writes=pending_commits;
            ProtectedLoop_PwmEntry(); assert(!cl_pwm_pending.valid && pending_commits==writes);
        } else if (which==6U) {
            motor_control_mode=MOTOR_MODE_IDLE; writes=pending_commits;
            ProtectedLoop_PwmEntry(); assert(!cl_pwm_pending.valid && pending_commits==writes);
        } else if (which==7U) {
            cl_session.outer_us=t2.CNT-2001U; ProtectedLoop_PwmEntry();
            off(); assert(cl_flags&CL_OUTER_STALE);
        } else if (which==8U) {
            t1.BDTR&=~TIM_BDTR_MOE; writes=pending_commits; ProtectedLoop_PwmEntry();
            off(); assert(cl_flags&CL_BAD_OUTPUT); assert(pending_commits==writes);
        } else if (which==9U) {
            pipeline_plan_matches=0U; assert(frame(1551U,1551U));
            off(); assert(cl_flags&CL_BAD_ADC);
        } else if (which==10U) {
            t2.CNT+=101U; ProtectedLoop_PwmEntry(); off(); assert(cl_flags&CL_BAD_ADC);
        } else if (which==11U) {
            cl_session.start_us=t2.CNT-CL_MAX_US; ProtectedLoop_PwmEntry();
            off(); assert(cl_session.state==CL_DONE && !cl_pwm_pending.valid);
        } else if (which==12U) {
            encoder_speed_rpm=61.0f; ProtectedLoop_PwmEntry(); off(); assert(cl_flags&CL_OVERSPEED);
        } else if (which==13U) {
            fw_update.active=1U; ProtectedLoop_PwmEntry(); off(); assert(cl_flags&CL_BAD_ADMISSION);
        }
    }
    LatestOriginal_FsmService();
    puts("PASS protected pipeline original START / neutral / one-cycle / hold / revocation");
}
