#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "tightening_intent_fsm.h"
#include "control_intent_port.h"
static TighteningFsm s;
static TighteningFsmInput in;
static unsigned calls[5];
static float target;
static void idle(void *p) {(void)p; ++calls[0];}
static void speed(void *p,float v) {(void)p; ++calls[1]; target=v;}
static void position(void *p,float v) {(void)p; ++calls[2]; target=v;}
static void iq(void *p,float v) {(void)p; ++calls[3]; target=v;}
static void stop(void *p) {(void)p; ++calls[4];}
static ControlIntentPort port;
static void reset(void)
{
    TighteningFsmConfig c={.recipe=TIGHTEN_PARAMS_DEFAULT_INITIALIZER,
        .direction=1,.speed_iq_limit_a=.4f,.direct_iq_limit_a=.2f,.hard_speed_limit_rpm=60,
        .stop_max_rpm=2,.stop_confirm_ms=150,.stop_timeout_ms=2000,.session_timeout_ms=12000};
    c.recipe.rundown_rpm=20; c.recipe.seating_ms=c.recipe.t1_ms=c.recipe.t2_ms=c.recipe.t3_ms=c.recipe.hold_ms=50;
    TighteningFsm_Init(&s,c,0);
    in=(TighteningFsmInput){.encoder_valid=1};
    memset(calls,0,sizeof calls); target=0;
    port=(ControlIntentPort){idle,speed,position,iq,stop,NULL,.4f,.2f,60,CONTROL_OFF};
}
static void tick(void)
{
    in.now_ms+=10; TighteningFsm_Step(&s,in);
    TrajectoryReference r=ControlIntent_Passthrough(s.intent);
    assert(ControlIntent_Apply(&port,&r.reference));
    if (TighteningFsm_IsFault(&s)) {
        assert(s.intent.control_mode==CONTROL_OFF && !s.intent.enable_current_loop);
        assert(s.intent.iq_target_a==0 && s.intent.speed_target_rpm==0);
    }
}
static void begin(void)
{
    in.start=1; tick(); in.start=0; assert(s.state==TF_PRECHECK);
    assert(s.intent.control_mode==CONTROL_OFF);
    in.precheck_ready=1; tick(); assert(s.state==TF_RUNDOWN_START);
    assert(s.intent.control_mode==CONTROL_SPEED && target==s.cfg.direction*20);
}
static void arm(void)
{
    begin(); in.speed_ctrl_rpm=in.speed_detect_rpm=20; in.iq_demand_a=.35f;
    for(unsigned i=0;i<12;++i) {in.position_deg+=.6f; tick();}
    assert(s.state==TF_RUNDOWN && s.rundown_armed);
}
static void contact(void)
{
    arm(); in.speed_ctrl_rpm=in.speed_detect_rpm=0;
    tick(); assert(s.state==TF_CONTACT_CONFIRM && s.contact_pending && !s.contact_confirmed);
    for(unsigned i=0;i<25;++i) tick();
    assert(s.state==TF_CONTACT_CONFIRM && s.contact_confirmed && !s.contact_pending);
    assert(s.intent.control_mode==CONTROL_NEUTRAL);
    for(unsigned i=0;i<16;++i) tick();
    assert(s.state==TF_TIGHTEN && s.intent.control_mode==CONTROL_IQ);
}
static void to_state(unsigned state)
{
    reset();
    if(state==TF_IDLE) return;
    if(state==TF_PRECHECK) {in.start=1; tick(); in.start=0; return;}
    if(state==TF_RUNDOWN_START) {begin(); return;}
    if(state==TF_RUNDOWN) {arm(); return;}
    if(state==TF_CONTACT_CONFIRM) {arm(); in.speed_ctrl_rpm=in.speed_detect_rpm=0; tick(); return;}
    contact();
    if(state==TF_TIGHTEN) return;
    while(s.state==TF_TIGHTEN) tick();
    assert(s.state==TF_HOLD);
    if(state==TF_HOLD) return;
    while(s.state==TF_HOLD) tick();
    assert(s.state==TF_DONE);
}
int main(void)
{
    reset(); contact();
    float phases[4]={.08f,.10f,.12f,.15f};
    for(unsigned p=0;p<4;++p) {
        assert(s.state==TF_TIGHTEN && s.phase==p);
        assert(fabsf(s.intent.iq_target_a-phases[p])<1e-6f);
        for(unsigned j=0;j<5;++j) tick();
    }
    assert(s.state==TF_HOLD && s.tightening_completed && s.intent.iq_target_a==.15f);
    for(unsigned j=0;j<5;++j) tick();
    assert(s.state==TF_DONE && s.outcome==TF_OUT_OK && s.rundown_armed && s.contact_confirmed);
    assert(s.intent.control_mode==CONTROL_OFF && calls[4]);
    in.position_deg+=100; tick(); assert(s.state==TF_DONE); /* frozen success, no re-evaluation */

    reset(); begin(); in.iq_demand_a=.4f;
    for(unsigned j=0;j<160 && !TighteningFsm_IsFault(&s);++j) tick();
    assert(s.state==TF_NO_ROTATION && s.fault_reason==TF_REASON_NO_ROTATION);
    assert(!s.contact_confirmed && s.outcome!=TF_OUT_OK);
    in.stop=1; tick(); assert(s.state==TF_NO_ROTATION); /* STOP cannot clear fault */

    reset(); begin(); in.speed_ctrl_rpm=in.speed_detect_rpm=20; in.position_deg=40; tick();
    in.speed_ctrl_rpm=in.speed_detect_rpm=0; in.iq_demand_a=.4f;
    for(unsigned j=0;j<100;++j) tick();
    assert(!s.rundown_armed && !s.contact_confirmed && s.state==TF_RUNDOWN_START);

    reset(); arm(); in.speed_ctrl_rpm=in.speed_detect_rpm=0; tick();
    for(unsigned j=0;j<10;++j) tick();
    in.speed_detect_rpm=13; tick(); assert(s.state==TF_RUNDOWN && !s.contact_confirmed);
    in.speed_detect_rpm=0; tick();
    for(unsigned j=0;j<24;++j) tick();
    assert(!s.contact_confirmed);
    tick(); assert(s.contact_confirmed);

    reset(); arm(); in.speed_ctrl_rpm=in.speed_detect_rpm=0; tick();
    for(unsigned j=0;j<20;++j) tick();
    in.speed_detect_rpm=11; tick(); assert(s.state==TF_CONTACT_CONFIRM && !s.contact_timer);
    in.speed_detect_rpm=0; tick();
    for(unsigned j=0;j<24;++j) tick();
    assert(!s.contact_confirmed);
    tick(); assert(s.contact_confirmed); /* hysteresis did not accumulate non-strict time */

    reset(); begin(); in.speed_ctrl_rpm=in.speed_detect_rpm=10; in.iq_demand_a=.35f;
    for(unsigned j=0;j<12;++j) {in.position_deg+=.4f; tick();}
    assert(s.rundown_armed && s.state==TF_RUNDOWN);
    for(unsigned j=0;j<30;++j) tick();
    assert(s.state==TF_RUNDOWN && !s.contact_pending); /* 10rpm steady is not a speed drop */
    in.speed_ctrl_rpm=in.speed_detect_rpm=6; tick(); assert(s.state==TF_CONTACT_CONFIRM);

    for(unsigned st=TF_IDLE;st<=TF_DONE;++st) {
        for(unsigned reason=TF_REASON_OVERSPEED;reason<=TF_REASON_FAULT;++reason) {
            to_state(st); in.protection_fault=(TighteningFsmReason)reason; in.stop=1; tick();
            assert(s.state==TF_FAULT && s.fault_reason==reason && s.intent.control_mode==CONTROL_OFF);
            assert(s.outcome!=TF_OUT_OK);
        }
        to_state(st); in.protection_fault=TF_REASON_ADC_HEALTH; in.stop=1; tick();
        assert(s.state==TF_FAULT && s.fault_reason==TF_REASON_ADC_HEALTH &&
               s.intent.control_mode==CONTROL_OFF && s.outcome!=TF_OUT_OK);
        to_state(st); in.stop=1; in.start=1; tick();
        assert(s.state==TF_IDLE && s.outcome==TF_OUT_STOPPED && s.intent.control_mode==CONTROL_OFF);
    }
    reset(); in.start=1; tick(); in.start=0;
    for(unsigned j=0;j<100;++j) tick();
    assert(s.state==TF_TIMEOUT);
    reset(); begin();
    for(unsigned j=0;j<805 && !TighteningFsm_IsFault(&s);++j) tick();
    assert(s.state==TF_TIMEOUT && !s.contact_confirmed);
    reset(); arm(); in.position_deg=3100; tick(); assert(s.state==TF_TIMEOUT);
    reset(); contact(); in.speed_ctrl_rpm=30; tick();
    assert(s.state==TF_FAULT && s.fault_reason==TF_REASON_TRAVEL);
    reset(); contact(); in.position_deg+=90; tick(); assert(s.state==TF_FAULT);
    reset(); begin(); in.encoder_valid=0; tick(); assert(s.fault_reason==TF_REASON_ENCODER_FAULT);
    reset(); begin(); in.speed_ctrl_rpm=NAN; tick(); assert(s.state==TF_FAULT);
    reset(); begin(); in.now_ms+=31; tick(); assert(s.state==TF_TIMEOUT);
    reset(); s.cfg.direction=-1; begin(); in.speed_ctrl_rpm=in.speed_detect_rpm=-20; in.iq_demand_a=-.35f;
    for(unsigned j=0;j<12;++j) {in.position_deg-=.6f; tick();}
    assert(s.state==TF_RUNDOWN && s.rundown_armed);
    reset(); to_state(TF_HOLD); s.tightening_completed=0;
    for(unsigned j=0;j<5;++j) tick();
    assert(s.state==TF_FAULT && s.outcome!=TF_OUT_OK);
    reset(); begin(); ControlIntent bad=s.intent; bad.iq_limit_a=.5f;
    unsigned previous=calls[1]; assert(!ControlIntent_Apply(&port,&bad)); assert(calls[1]==previous);
    bad=s.intent; bad.hold_integrators=1; assert(!ControlIntent_Apply(&port,&bad));
    bad=s.intent; bad.control_mode=CONTROL_POSITION; assert(!ControlIntent_Apply(&port,&bad));
    reset(); s.last_ms=in.now_ms=UINT32_MAX-50U; begin();
    in.speed_ctrl_rpm=in.speed_detect_rpm=20; in.iq_demand_a=.35f;
    for(unsigned j=0;j<12;++j) {in.position_deg+=.6f; tick();}
    assert(s.rundown_armed && in.now_ms<1000U);
    ControlAlgorithmExtensions reserved={0};
    assert(!reserved.trajectory_generator && !reserved.dob && !reserved.friction_feedforward);
    puts("intent FSM + backend contract: all scenarios PASS");
    return 0;
}
