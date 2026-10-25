/* Task-only port. Core FSM has no controller/PWM/HAL dependency.
 * UART START/STOP correlation, recipe storage ABI and protected admission
 * remain owned by their existing services. Never invoked by the ADC ISR. */
#include "control_intent_port.h"
#pragma GCC push_options
#pragma GCC optimize ("Oz")
static uint8_t TighteningIntent_PrecheckOnly(void)
{
    return intent_fsm.state==TF_PRECHECK && intent_fsm.intent.control_mode==CONTROL_OFF &&
        !intent_fsm.intent.enable_current_loop && !intent_fsm.intent.enable_speed_loop &&
        !intent_fsm.intent.enable_position_loop;
}
static void IntentPort_Idle(void *p) { (void)p; MotorControl_SetIdle(); }
static void IntentPort_Speed(void *p,float rpm) { (void)p; MotorControl_SetSpeed(rpm); }
static void IntentPort_Iq(void *p,float iq) { (void)p; MotorControl_SetIq(iq); }
static void IntentPort_Stop(void *p)
{
    (void)p;
    if (cl_session.state==CL_RUNNING) ProtectedLoop_Stop();
}
static TighteningFsmConfig IntentPort_Config(void)
{
    TighteningFsmConfig cfg={.direction=TIGHTEN_DIRECTION,
        .speed_iq_limit_a=MOTOR_SPEED_IQ_LIMIT_A,.direct_iq_limit_a=MOTOR_DIRECT_IQ_LIMIT_A,
        .hard_speed_limit_rpm=CL_OVERSPEED_RPM,.stop_max_rpm=TIGHTEN_STOP_MAX_RPM,
        .stop_confirm_ms=TIGHTEN_STOP_CONFIRM_MS,.stop_timeout_ms=TIGHTEN_STOP_TIMEOUT_MS,
        .session_timeout_ms=CL_MAX_US/1000U};
    taskENTER_CRITICAL(); cfg.recipe=recipe_state.params; taskEXIT_CRITICAL();
    return cfg;
}
static TighteningFsmReason IntentPort_Fault(void)
{
    /* Safety closes the session BEFORE the task observes it. Never replace
     * that latched cause with the secondary loss-of-session symptom. */
    if (!(adc_fault || foc_fault || cl_fault_valid)) {
        if (TighteningFsm_Busy(&intent_fsm) && intent_fsm.state!=TF_PRECHECK &&
                cl_session.state!=CL_RUNNING && !tightening_stop_request)
            return TF_REASON_TIMEOUT;
        return TF_REASON_NONE;
    }
    if (cl_flags & CL_OVERSPEED) return TF_REASON_OVERSPEED;
    if (cl_flags & CL_BAD_ENCODER) return TF_REASON_ENCODER_FAULT;
    if (cl_safety.protection.reason==FOC_FP_CURRENT_INVALID) return TF_REASON_CURRENT_INVALID;
    if (cl_safety.protection.reason==FOC_FP_CONFIRMED_CURRENT ||
            (cl_safety.protection.reason==FOC_FP_HARDWARE &&
             (cl_safety.protection.fault_flags & FOC_FP_HW_TRIP))) return TF_REASON_OVERCURRENT;
    if (cl_safety.protection.reason==FOC_FP_TIMEOUT ||
            (cl_flags & (CL_COMPUTE_LATE|CL_OUTER_STALE))) return TF_REASON_TIMEOUT;
    if (adc_fault || (cl_flags & CL_BAD_ADC)) return TF_REASON_ADC_HEALTH;
    if (foc_fault_reason==3U) return TF_REASON_OVERSPEED;
    if (foc_fault_reason==2U) return TF_REASON_ENCODER_FAULT;
    return TF_REASON_FAULT;
}
static TighteningStageResult_t *IntentPort_Result(uint8_t phase)
{
    switch (phase) {
    case 0: return &tighten_result_seating;
    case 1: return &tighten_result_010;
    case 2: return &tighten_result_012;
    case 3: return &tighten_result_015;
    default: return &tighten_result_hold;
    }
}
static void IntentPort_LegacyView(uint32_t now)
{
    switch (intent_fsm.state) {
    case TF_IDLE: case TF_PRECHECK: tightening_test_stage=TIGHTEN_STATE_IDLE_DELAY; break;
    case TF_RUNDOWN_START: case TF_RUNDOWN: tightening_test_stage=TIGHTEN_STATE_RUNDOWN; break;
    case TF_CONTACT_CONFIRM:
        tightening_test_stage=intent_fsm.contact_confirmed ? TIGHTEN_STATE_CONTACT_STOP : TIGHTEN_STATE_RUNDOWN; break;
    case TF_TIGHTEN: tightening_test_stage=(TighteningTestStage_t)(TIGHTEN_STATE_SEATING_IQ+intent_fsm.phase); break;
    case TF_HOLD: tightening_test_stage=TIGHTEN_STATE_HOLD; break;
    case TF_DONE: tightening_test_stage=TIGHTEN_STATE_DONE; break;
    case TF_TIMEOUT: tightening_test_stage=TIGHTEN_STATE_TIMEOUT; break;
    default: tightening_test_stage=TIGHTEN_STATE_FAULT; break;
    }
    tightening_test_elapsed_ms=now-intent_fsm.entered_ms;
    tightening_contact_confirmed=intent_fsm.contact_confirmed;
    tightening_contact_condition=intent_fsm.contact_pending;
    tightening_contact_candidate_ms=intent_fsm.contact_pending_ms;
    tightening_rundown.state=intent_fsm.rundown_armed ? RUNDOWN_ARMED : RUNDOWN_NOT_ESTABLISHED;
    tightening_travel_deg=fabsf(encoder_position_deg-intent_fsm.start_position);
    tightening_start_position_deg=intent_fsm.start_position;
    tightening_contact_position_deg=intent_fsm.contact_position;
    tightening_post_contact_travel_deg=fabsf(encoder_position_deg-intent_fsm.contact_position);
    tightening_drive_iqref_A=TIGHTEN_DIRECTION*foc_iq_ref_A;
}
static void TighteningIntent_PrintStatus(uint32_t request_id)
{
    char msg[256]; TighteningFsmState state,prev; TighteningFsmReason reason;
    TighteningFsmOutcome outcome; ControlIntent intent; uint32_t elapsed_ms;
    float travel; uint8_t armed,pending,confirmed;
    taskENTER_CRITICAL();
    state=intent_fsm.state; prev=intent_fsm.previous_state; reason=intent_fsm.fault_reason;
    outcome=intent_fsm.outcome; intent=intent_fsm.intent;
    elapsed_ms=(uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS)-intent_fsm.entered_ms;
    travel=intent_fsm.motion_travel_deg; armed=intent_fsm.rundown_armed;
    pending=intent_fsm.contact_pending; confirmed=intent_fsm.contact_confirmed;
    taskEXIT_CRITICAL();
    /* Supplemental event lines: original STATUS ACK/fields stay intact. */
    Protocol_SendFormatted(msg,sizeof msg,
        "0 EVT FSM REQ=%lu FSM_STATE=%s PREV_STATE=%s STATE_TIME_MS=%lu RUNDOWN_ARMED=%u CONTACT_PENDING=%u CONTACT_CONFIRMED=%u\r\n",
        (unsigned long)request_id,TighteningFsm_StateName(state),TighteningFsm_StateName(prev),
        (unsigned long)elapsed_ms,armed,pending,confirmed);
    Protocol_SendFormatted(msg,sizeof msg,
        "0 EVT FSM REQ=%lu MOTION_TRAVEL_DEG=%ldmdeg SPEED_TARGET=%ldmrpm IQ_LIMIT=%ldmA CONTROL_MODE=%u OUTCOME=%s FAULT_REASON=%s\r\n",
        (unsigned long)request_id,(long)(travel*1000.0f),(long)(intent.speed_target_rpm*1000.0f),
        (long)(intent.iq_limit_a*1000.0f),intent.control_mode,
        TighteningFsm_OutcomeName(outcome),TighteningFsm_ReasonName(reason));
}
static void IntentPort_ReportTerminal(void)
{
    if (tightening_result_printed || intent_fsm.outcome==TF_OUT_NONE) return;
    const char *name=intent_fsm.outcome==TF_OUT_OK ? "OK" :
        intent_fsm.outcome==TF_OUT_STOPPED ? "STOPPED" : TighteningFsm_ReasonName(intent_fsm.fault_reason);
    tightening_last_outcome=intent_fsm.outcome==TF_OUT_OK ? TIGHTEN_OUTCOME_OK :
        intent_fsm.outcome==TF_OUT_STOPPED ? TIGHTEN_OUTCOME_STOPPED :
        intent_fsm.fault_reason==TF_REASON_NO_ROTATION ? TIGHTEN_OUTCOME_NO_ROTATION :
        intent_fsm.fault_reason==TF_REASON_STOP_TIMEOUT ? TIGHTEN_OUTCOME_STOP_TIMEOUT :
        intent_fsm.fault_reason==TF_REASON_TRAVEL ? TIGHTEN_OUTCOME_ABORT :
        intent_fsm.state==TF_TIMEOUT ? TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT : TIGHTEN_OUTCOME_FAULT;
    if (intent_fsm.outcome==TF_OUT_FAILED && !foc_fault_snapshot.valid)
        FaultDiag_Capture(FOC_DIAG_PROCESS,(uint32_t)tightening_last_outcome,
            FOC_TO_NONE,tightening_test_elapsed_ms,0U);
    if (g_tightening_session_active) Protocol_SendCycleEvent("COMPLETE",name);
    tightening_result_printed=1U; TighteningResult_PrintSummary(name);
    if (intent_fsm.outcome==TF_OUT_OK) TighteningRepeat_StoreCurrentCycle();
}
static void TighteningTask(void *argument)
{
    (void)argument; TickType_t wake=xTaskGetTickCount();
    ControlIntentPort port={IntentPort_Idle,IntentPort_Speed,NULL,
        IntentPort_Iq,IntentPort_Stop,NULL,MOTOR_SPEED_IQ_LIMIT_A,MOTOR_DIRECT_IQ_LIMIT_A,
        CL_OVERSPEED_RPM,CONTROL_OFF};
    TighteningFsm_Init(&intent_fsm,IntentPort_Config(),(uint32_t)(wake*portTICK_PERIOD_MS));
    tightening_start_request=tightening_stop_request=tightening_result_request=0U;
    tightening_last_outcome=TIGHTEN_OUTCOME_NONE; tightening_result_printed=1U;
    MotorControl_SetIdle();
    UART_SendLiteral("TIGHTEN: INTENT_FSM_CANDIDATE; manual START only\r\n");
    for (;;) {
        uint32_t now=(uint32_t)(xTaskGetTickCount()*portTICK_PERIOD_MS);
        TighteningFsmInput in={.now_ms=now,.position_deg=encoder_position_deg,
            .speed_ctrl_rpm=encoder_speed_rpm,.speed_detect_rpm=encoder_speed_detect_rpm,
            .iq_demand_a=foc_iq_ref_A,.encoder_valid=encoder_valid,
            .protection_fault=IntentPort_Fault()};
        uint8_t had_start=0U; uint32_t stop_req=0U;
        if (tightening_stop_request) {
            __DMB(); stop_req=tightening_stop_request_id;
            in.stop=1U; tightening_stop_request=0U; tightening_stop_request_id=0U;
            /* A simultaneous pending START is cancelled, never run after STOP. */
            tightening_start_request=0U; tightening_start_request_id=0U;
        } else if (tightening_start_request) {
            __DMB(); uint32_t req=tightening_start_request_id;
            uint8_t routed=tightening_start_request_routed;
            uint16_t source=tightening_start_request_source_node;
            tightening_start_request=0U; tightening_start_request_id=0U;
            tightening_start_request_routed=0U; tightening_start_request_source_node=0U;
            const char *error=in.protection_fault ? "FAULT" :
                TighteningFsm_Busy(&intent_fsm) ? "BUSY" :
                TighteningFsm_IsFault(&intent_fsm) ? "FAULT" : routed ? "LATEST_BACKEND_NOT_READY" :
                SystemPreflight_FailMask() ? "PREFLIGHT_NOT_READY" : NULL;
            if (error) Protocol_SendDeferredStartError(routed,source,req,error);
            else {
                TighteningFsmConfig cfg=IntentPort_Config();
                taskENTER_CRITICAL(); intent_fsm.cfg=cfg; taskEXIT_CRITICAL();
                tightening_cycle_request_id=req; TighteningSession_Begin(routed,source,req);
                memset(tightening_cycle_summary,0,sizeof tightening_cycle_summary);
                tightening_cycle_number=1U; tightening_cycle_ok_count=0U;
                TighteningRepeat_ResetCurrentCycle(); tightening_last_outcome=TIGHTEN_OUTCOME_NONE;
                tightening_result_printed=0U; in.start=1U; had_start=1U;
            }
        }
        /* Only the backend port owns admission. PRECHECK is output-OFF and
         * all existing health/recipe/neutral/freshness gates are rechecked. */
        if (!in.stop && intent_fsm.state==TF_PRECHECK &&
                !in.protection_fault && !SystemPreflight_FailMask()) {
            in.precheck_ready=LatestOriginal_Admit();
            if (!in.precheck_ready) in.protection_fault=TF_REASON_INTENT_REJECTED;
        }
        TighteningFsmState before=intent_fsm.state; uint8_t phase=intent_fsm.phase;
        taskENTER_CRITICAL();
        TighteningFsm_Step(&intent_fsm,in);
        TrajectoryReference reference=ControlIntent_Passthrough(intent_fsm.intent);
        taskEXIT_CRITICAL();
        if (!ControlIntent_Apply(&port,&reference.reference)) {
            /* Reject unsupported intent, never silently reinterpret limits. */
            IntentPort_Stop(NULL); MotorControl_SetIdle();
            taskENTER_CRITICAL(); TighteningFsm_Reject(&intent_fsm,TF_REASON_INTENT_REJECTED,now); taskEXIT_CRITICAL();
        }
        if (before==TF_PRECHECK && intent_fsm.state==TF_RUNDOWN_START) {
            char event[128]; snprintf(event,sizeof event,"EVT REQ=%lu STARTED MODE=RUNDOWN TARGET=%lurpm",
                (unsigned long)tightening_cycle_request_id,(unsigned long)intent_fsm.cfg.recipe.rundown_rpm);
            Protocol_AsyncEventEnqueue(g_tightening_session_routed,g_tightening_session_owner_node,event);
        }
        IntentPort_LegacyView(now);
        if (in.stop) {
            char msg[96]; Protocol_SendFormatted(msg,sizeof msg,"EVT REQ=%lu STOPPED START_REQ=%lu\r\n",
                (unsigned long)stop_req,(unsigned long)tightening_cycle_request_id);
        }
        if (intent_fsm.state==TF_TIGHTEN || intent_fsm.state==TF_HOLD) {
            uint8_t slot=intent_fsm.state==TF_HOLD ? 4U : intent_fsm.phase;
            TighteningStageResult_t *result=IntentPort_Result(slot);
            if (before!=intent_fsm.state || phase!=intent_fsm.phase)
                TighteningResult_Reset(result,fabsf(intent_fsm.intent.iq_target_a));
            TighteningResult_Sample(result);
        }
        if (!TighteningFsm_Busy(&intent_fsm) && !had_start) IntentPort_ReportTerminal();
        if (tightening_result_request) {
            char msg[160]; uint32_t req=tightening_result_request_id;
            tightening_result_request=0U; tightening_result_request_id=0U;
            if (TighteningFsm_Busy(&intent_fsm)) Protocol_SendError(req,PROTO_ERR_BUSY,"BUSY");
            else {
                Protocol_SendFormatted(msg,sizeof msg,"%lu OK RESULT DATA START_REQ=%lu OUTCOME=%s CONTACT=%u\r\n",
                    (unsigned long)req,(unsigned long)tightening_cycle_request_id,
                    TighteningOutcome_Name(tightening_last_outcome),tightening_contact_confirmed);
                TighteningResult_PrintSummary(TighteningOutcome_Name(tightening_last_outcome));
                Protocol_SendFormatted(msg,sizeof msg,"%lu END RESULT\r\n",(unsigned long)req);
            }
        }
        LatestOriginal_FsmService();
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(10U));
    }
}
#pragma GCC pop_options
