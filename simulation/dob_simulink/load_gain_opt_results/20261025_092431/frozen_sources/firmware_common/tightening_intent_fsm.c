#include "tightening_intent_fsm.h"
#include <math.h>
#include <string.h>

static uint32_t elapsed(uint32_t now,uint32_t then) { return now-then; }
uint8_t TighteningFsm_Busy(const TighteningFsm *s)
{ return s->state>=TF_PRECHECK && s->state<=TF_HOLD; }
uint8_t TighteningFsm_IsFault(const TighteningFsm *s)
{ return s->state==TF_FAULT || s->state==TF_NO_ROTATION || s->state==TF_TIMEOUT; }
static void fsm_enter_tighten_phase(TighteningFsm *s,uint8_t phase,uint32_t now)
{ s->phase=phase; s->phase_ms=now; }
static void fsm_enter_contact_settle(TighteningFsm *s,uint32_t now,float position)
{
    s->contact_confirmed=1U; s->contact_pending=0U;
    s->contact_confirmed_ms=now; s->contact_position=position;
    s->contact_timer=0U; s->contact_pending_ms=0U;
    s->intent.reset_speed_integrator=1U;
}

/* The sole state entry/exit owner. No PI/PWM/HAL/RTOS/formatting dependency. */
static void fsm_enter_state(TighteningFsm *s,TighteningFsmState next,uint32_t now,float position)
{
    s->previous_state=s->state; s->state=next; s->entered_ms=now; ++s->transition_count;
    s->contact_timer=s->settle_timer=0U; s->contact_pending_ms=0U;
    s->contact_pending=(uint8_t)(next==TF_CONTACT_CONFIRM);
    if (next==TF_PRECHECK || next==TF_IDLE) {
        TightenRundown_Begin(&s->motion);
        s->rundown_armed=s->contact_confirmed=s->tightening_completed=0U;
        s->start_position=position; s->contact_position=position; s->motion_travel_deg=0.0f;
        s->rundown_peak_speed_rpm=0.0f;
        s->phase=0U; s->fault_reason=TF_REASON_NONE;
        if (next==TF_PRECHECK) { s->outcome=TF_OUT_NONE; s->cycle_ms=now; }
    }
    if (next==TF_RUNDOWN_START) { s->rundown_ms=now; s->start_position=position; }
    if (next==TF_RUNDOWN) s->rundown_armed=1U;
    if (next==TF_TIGHTEN) fsm_enter_tighten_phase(s,0U,now);
    if (next==TF_DONE) {
        if (s->rundown_armed && s->contact_confirmed && s->tightening_completed &&
                s->fault_reason==TF_REASON_NONE) s->outcome=TF_OUT_OK;
        else { s->state=TF_FAULT; s->fault_reason=TF_REASON_FAULT; s->outcome=TF_OUT_FAILED; }
    }
    s->intent=(ControlIntent){0};
    s->intent.reset_position_integrator=(uint8_t)(next==TF_IDLE || next==TF_PRECHECK ||
        next==TF_RUNDOWN_START || next==TF_TIGHTEN);
    s->intent.reset_speed_integrator=s->intent.reset_position_integrator;
}
static void fail(TighteningFsm *s,TighteningFsmReason reason,uint32_t now)
{
    fsm_enter_state(s,reason==TF_REASON_NO_ROTATION ? TF_NO_ROTATION :
        (reason==TF_REASON_TIMEOUT || reason==TF_REASON_STOP_TIMEOUT ? TF_TIMEOUT : TF_FAULT),now,s->start_position);
    s->fault_reason=reason; s->outcome=TF_OUT_FAILED;
}
void TighteningFsm_Reject(TighteningFsm *s,TighteningFsmReason why,uint32_t now)
{ if (!TighteningFsm_IsFault(s)) fail(s,why,now); }
void TighteningFsm_Init(TighteningFsm *s,TighteningFsmConfig cfg,uint32_t now)
{
    *s=(TighteningFsm){0}; s->cfg=cfg; s->last_ms=now;
    fsm_enter_state(s,TF_IDLE,now,0.0f);
}
static int config_ok(const TighteningFsmConfig *c)
{
    return (c->direction==1.0f || c->direction==-1.0f) &&
        isfinite(c->speed_iq_limit_a) && c->speed_iq_limit_a>0.0f &&
        isfinite(c->direct_iq_limit_a) && c->direct_iq_limit_a>0.0f &&
        isfinite(c->hard_speed_limit_rpm) && c->hard_speed_limit_rpm>0.0f &&
        isfinite(c->stop_max_rpm) && c->stop_max_rpm>0.0f && c->stop_timeout_ms &&
        c->stop_confirm_ms && c->session_timeout_ms && TightenParams_Validate(&c->recipe) &&
        c->recipe.rundown_rpm<c->hard_speed_limit_rpm;
}
static void output(TighteningFsm *s)
{
    uint8_t rp=s->intent.reset_position_integrator,rs=s->intent.reset_speed_integrator;
    s->intent=(ControlIntent){0}; s->intent.reset_position_integrator=rp; s->intent.reset_speed_integrator=rs;
    if (s->state==TF_RUNDOWN_START || s->state==TF_RUNDOWN ||
            (s->state==TF_CONTACT_CONFIRM && !s->contact_confirmed)) {
        s->intent.control_mode=CONTROL_SPEED;
        s->intent.speed_target_rpm=s->cfg.direction*(float)s->cfg.recipe.rundown_rpm;
        s->intent.iq_limit_a=s->cfg.speed_iq_limit_a;
        s->intent.speed_limit_rpm=s->cfg.hard_speed_limit_rpm;
        s->intent.enable_speed_loop=s->intent.enable_current_loop=1U;
    } else if (s->state==TF_TIGHTEN || s->state==TF_HOLD) {
        const TightenParams_t *p=&s->cfg.recipe;
        const uint32_t currents[4]={p->seating_iq_mA,p->t1_iq_mA,p->t2_iq_mA,p->t3_iq_mA};
        s->intent.control_mode=CONTROL_IQ;
        s->intent.iq_target_a=s->cfg.direction*(float)(s->state==TF_HOLD ? p->hold_iq_mA : currents[s->phase])*0.001f;
        s->intent.iq_limit_a=s->cfg.direct_iq_limit_a;
        s->intent.speed_limit_rpm=(float)p->torque_abort_rpm;
        s->intent.enable_current_loop=1U;
    } else if (s->state==TF_CONTACT_CONFIRM && s->contact_confirmed) {
        /* Existing stop-settle: zero-current neutral while session remains
         * admitted. Not a fault/off request or a new power-enable path. */
        s->intent.control_mode=CONTROL_NEUTRAL; s->intent.enable_current_loop=1U;
        s->intent.iq_limit_a=s->cfg.direct_iq_limit_a;
        s->intent.speed_limit_rpm=s->cfg.hard_speed_limit_rpm;
    }
}
void TighteningFsm_Step(TighteningFsm *s,TighteningFsmInput in)
{
    uint8_t was_torque=(uint8_t)(s->state==TF_TIGHTEN || s->state==TF_HOLD);
    uint32_t gap=elapsed(in.now_ms,s->last_ms); s->last_ms=in.now_ms;
    s->intent.reset_position_integrator=s->intent.reset_speed_integrator=0U;
    /* Protection wins STOP/START. Never clear a latched failure with STOP. */
    if (in.protection_fault!=TF_REASON_NONE) {
        if (!TighteningFsm_IsFault(s)) {
            fsm_enter_state(s,TF_FAULT,in.now_ms,s->start_position);
            s->fault_reason=in.protection_fault; s->outcome=TF_OUT_FAILED;
        }
        output(s); return;
    }
    if (TighteningFsm_IsFault(s)) { output(s); return; }
    if (in.stop) {
        fsm_enter_state(s,TF_IDLE,in.now_ms,in.position_deg);
        s->outcome=TF_OUT_STOPPED; output(s); return;
    }
    if (TighteningFsm_Busy(s)) {
        if (!in.encoder_valid || !isfinite(in.position_deg) || !isfinite(in.speed_ctrl_rpm) ||
                !isfinite(in.speed_detect_rpm) || !isfinite(in.iq_demand_a)) {
            fail(s,TF_REASON_ENCODER_FAULT,in.now_ms); output(s); return;
        }
        if (gap>TIGHTEN_FSM_MAX_OBSERVATION_GAP_MS ||
                elapsed(in.now_ms,s->cycle_ms)>=s->cfg.session_timeout_ms) {
            fail(s,TF_REASON_TIMEOUT,in.now_ms); output(s); return;
        }
        s->motion_travel_deg=s->cfg.direction*(in.position_deg-s->start_position);
    }
    const TightenParams_t *p=&s->cfg.recipe;
    if (s->state==TF_RUNDOWN_START || s->state==TF_RUNDOWN) {
        float forward=fminf(s->cfg.direction*in.speed_ctrl_rpm,s->cfg.direction*in.speed_detect_rpm);
        if (forward>s->rundown_peak_speed_rpm) s->rundown_peak_speed_rpm=forward;
    }
    float contact_speed=fminf((float)p->contact_rpm,
        s->rundown_peak_speed_rpm*TIGHTEN_FSM_CONTACT_DROP_RATIO);
    switch (s->state) {
    case TF_IDLE: case TF_DONE:
        if (in.start) {
            fsm_enter_state(s,TF_PRECHECK,in.now_ms,in.position_deg);
            if (!config_ok(&s->cfg)) fail(s,TF_REASON_PRECHECK,in.now_ms);
        }
        break;
    case TF_PRECHECK:
        if (in.precheck_ready) fsm_enter_state(s,TF_RUNDOWN_START,in.now_ms,in.position_deg);
        else if (elapsed(in.now_ms,s->entered_ms)>=TIGHTEN_FSM_PRECHECK_TIMEOUT_MS)
            fail(s,TF_REASON_TIMEOUT,in.now_ms);
        break;
    case TF_RUNDOWN_START:
        if (TightenRundown_Update(&s->motion,elapsed(in.now_ms,s->rundown_ms),
                s->cfg.direction*(float)p->rundown_rpm,in.speed_ctrl_rpm,in.speed_detect_rpm,
                in.position_deg,in.iq_demand_a,in.encoder_valid))
            fail(s,TF_REASON_NO_ROTATION,in.now_ms);
        else if (TightenRundown_CanContact(&s->motion)) {
            fsm_enter_state(s,TF_RUNDOWN,in.now_ms,in.position_deg);
        }
        break;
    case TF_RUNDOWN:
        if (s->rundown_armed && fabsf(in.speed_detect_rpm)<=contact_speed &&
                s->cfg.direction*in.iq_demand_a>=(float)p->contact_iq_mA*0.001f) {
            fsm_enter_state(s,TF_CONTACT_CONFIRM,in.now_ms,in.position_deg);
            s->contact_timer=1U; s->contact_since_ms=in.now_ms;
        }
        break;
    case TF_CONTACT_CONFIRM:
        if (!s->rundown_armed) { fail(s,TF_REASON_NO_ROTATION,in.now_ms); break; }
        if (!s->contact_confirmed) {
            float load=s->cfg.direction*in.iq_demand_a;
            if (fabsf(in.speed_detect_rpm)>contact_speed+TIGHTEN_FSM_CONTACT_SPEED_HYST_RPM ||
                    load<(float)p->contact_iq_mA*0.001f-TIGHTEN_FSM_CONTACT_IQ_HYST_A) {
                fsm_enter_state(s,TF_RUNDOWN,in.now_ms,in.position_deg);
            } else if (fabsf(in.speed_detect_rpm)<=contact_speed &&
                    load>=(float)p->contact_iq_mA*0.001f) {
                if (!s->contact_timer) { s->contact_timer=1U; s->contact_since_ms=in.now_ms; }
                s->contact_pending_ms=elapsed(in.now_ms,s->contact_since_ms);
                if (s->contact_pending_ms>=p->contact_ms) {
                    fsm_enter_contact_settle(s,in.now_ms,in.position_deg);
                }
            } else { s->contact_timer=0U; s->contact_pending_ms=0U; }
        } else {
            if (fabsf(in.speed_ctrl_rpm)<=s->cfg.stop_max_rpm) {
                if (!s->settle_timer) { s->settle_timer=1U; s->settle_since_ms=in.now_ms; }
                if (elapsed(in.now_ms,s->settle_since_ms)>=s->cfg.stop_confirm_ms)
                    fsm_enter_state(s,TF_TIGHTEN,in.now_ms,in.position_deg);
            } else s->settle_timer=0U;
            if (s->state==TF_CONTACT_CONFIRM && elapsed(in.now_ms,s->contact_confirmed_ms)>=s->cfg.stop_timeout_ms)
                fail(s,TF_REASON_STOP_TIMEOUT,in.now_ms);
        }
        break;
    case TF_TIGHTEN: {
        const uint32_t times[4]={p->seating_ms,p->t1_ms,p->t2_ms,p->t3_ms};
        if (elapsed(in.now_ms,s->phase_ms)>=times[s->phase]) {
            if (s->phase<3U) fsm_enter_tighten_phase(s,s->phase+1U,in.now_ms);
            else { s->tightening_completed=1U; fsm_enter_state(s,TF_HOLD,in.now_ms,in.position_deg); }
        }
        break;
    }
    case TF_HOLD:
        if (elapsed(in.now_ms,s->entered_ms)>=p->hold_ms)
            fsm_enter_state(s,TF_DONE,in.now_ms,in.position_deg);
        break;
    default: fail(s,TF_REASON_FAULT,in.now_ms); break;
    }
    /* Safety boundaries win a coincident process-success transition. */
    if ((s->state==TF_RUNDOWN_START || s->state==TF_RUNDOWN ||
            (s->state==TF_CONTACT_CONFIRM && !s->contact_confirmed)) &&
            (elapsed(in.now_ms,s->rundown_ms)>=p->rundown_timeout_ms ||
             fabsf(in.position_deg-s->start_position)>=(float)p->max_travel_deg))
        fail(s,TF_REASON_TIMEOUT,in.now_ms);
    if ((s->state==TF_TIGHTEN || s->state==TF_HOLD || (s->state==TF_DONE && was_torque)) &&
            (fabsf(in.speed_ctrl_rpm)>=(float)p->torque_abort_rpm ||
             fabsf(in.position_deg-s->contact_position)>=(float)p->post_travel_max_deg))
        fail(s,TF_REASON_TRAVEL,in.now_ms);
    output(s);
}
const char *TighteningFsm_StateName(TighteningFsmState state)
{
    static const char *const names[]={"IDLE","PRECHECK","RUNDOWN_START","RUNDOWN",
        "CONTACT_CONFIRM","TIGHTEN","HOLD","DONE","NO_ROTATION","TIMEOUT","FAULT"};
    return (unsigned)state<sizeof(names)/sizeof(names[0]) ? names[state] : "FAULT";
}
const char *TighteningFsm_ReasonName(TighteningFsmReason reason)
{
    static const char *const names[]={"NONE","NO_ROTATION","OVERSPEED","OVERCURRENT",
        "CURRENT_INVALID","ENCODER_FAULT","TIMEOUT","FAULT","PRECHECK","TRAVEL",
        "STOP_TIMEOUT","INTENT_REJECTED","ADC_HEALTH"};
    return (unsigned)reason<sizeof(names)/sizeof(names[0]) ? names[reason] : "FAULT";
}
const char *TighteningFsm_OutcomeName(TighteningFsmOutcome outcome)
{
    static const char *const names[]={"NONE","OK","STOPPED","FAILED"};
    return (unsigned)outcome<sizeof(names)/sizeof(names[0]) ? names[outcome] : "FAILED";
}
