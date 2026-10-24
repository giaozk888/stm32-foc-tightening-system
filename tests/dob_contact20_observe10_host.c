#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "dob_normal_control.h"
#include "tightening_intent_fsm.h"

static MechanicalDobMonitor mon;
static DobFeedbackCandidate feedback={.enabled=1};
static uint32_t stamp=1000,seq=20;
static void observe(float rpm,uint8_t saturated){
    float w=rpm*.10471975511965977f;
    const MechanicalNormalizedModel *m=&mechanical_dob_identified_model;
    float iq=m->b_over_kt*w+m->coulomb_over_kt*(w>0?1.f:-1.f)+m->bias_a+(w>0?.02f:-.02f);
    DobNormal_Lifecycle(&mon,&feedback,1,0);
    uint8_t good=(uint8_t)(mon.current.valid&&mon.running&&!mon.frozen&&
        DobObserve10_FeedbackSpeedQualified(mon.current.omega_rad_s));
    DobFeedback_Update(&feedback,stamp+20,1000,mon.current.sample_us,mon.current.disturbance_a,good,1,.5f);
    MechanicalCurrent c={2,seq,stamp-20,stamp,.005f,iq,0};
    MechanicalDobMonitor_Observe(&mon,stamp+20,stamp,1000,w,saturated,&c,1);
    stamp+=1000;seq+=20;
}
static void observer_checks(void){
    assert(fabsf(mechanical_dob_identified_model.min_speed_rad_s-1.0471975512f)<1e-7f);
    assert(!DobObserve10_FeedbackSpeedQualified(NAN));
    for(int sign=-1;sign<=1;sign+=2){
        DobNormal_Lifecycle(&mon,&feedback,0,0);
        for(unsigned i=0;i<1500;i++)observe(15.f*sign,0);
        assert(mon.current.valid&&fabsf(mon.current.disturbance_a-.02f*sign)<1e-5f);
        assert(!feedback.iq_comp_a&&!feedback.have_valid);
        for(unsigned i=0;i<1500;i++)observe(10.f*sign,0);
        assert(mon.current.valid&&!feedback.iq_comp_a);
        for(unsigned i=0;i<1500;i++)observe(20.f*sign,0);
        assert(mon.current.valid&&fabsf(feedback.iq_comp_a-.005f*sign)<1e-5f);
        observe(15.f*sign,0); /* Existing pipeline may consume the preceding20rpm frame once. */
        unsigned fresh=feedback.valid_updates;
        for(unsigned i=0;i<24;i++)observe(15.f*sign,0);
        assert(mon.current.valid&&!feedback.iq_comp_a);
        assert(feedback.valid_updates==fresh); /* No fresh10..20rpm current injection. */
        for(unsigned i=0;i<30;i++)observe(9.9f*sign,0);
        assert(!mon.current.valid&&!feedback.iq_comp_a);
        for(unsigned i=0;i<1500;i++)observe(15.f*sign,0);
        assert(mon.current.valid);
        observe(15.f*sign,1);assert(!mon.current.valid); /* Existing saturation gate preserved. */
    }
}

static TighteningFsm fsm;
static TighteningFsmInput in;
static void tick(void){in.now_ms+=10;TighteningFsm_Step(&fsm,in);}
static void arm(void){
    TighteningFsmConfig cfg={.recipe=TIGHTEN_PARAMS_DEFAULT_INITIALIZER,.direction=1,
        .speed_iq_limit_a=.5f,.direct_iq_limit_a=.2f,.hard_speed_limit_rpm=300,
        .stop_max_rpm=2,.stop_confirm_ms=100,.stop_timeout_ms=2000,.session_timeout_ms=12000};
    /* Native persistent recipe remains unchanged. A startup overlay supplies20. */
    assert(cfg.recipe.contact_rpm==10U);
    cfg.recipe.contact_rpm=DOB_CONTACT20_RPM;
    TighteningFsm_Init(&fsm,cfg,0);in=(TighteningFsmInput){.encoder_valid=1,.start=1};
    tick();in.start=0;in.precheck_ready=1;tick();
    in.speed_ctrl_rpm=in.speed_detect_rpm=80;in.iq_demand_a=.35f;
    for(unsigned i=0;i<12;i++){in.position_deg+=1;tick();}
    assert(fsm.state==TF_RUNDOWN&&fsm.rundown_armed);
}
static void contact_checks(void){
    arm();in.speed_ctrl_rpm=in.speed_detect_rpm=20.01f;in.iq_demand_a=.30f;tick();
    assert(fsm.state==TF_RUNDOWN);
    in.speed_ctrl_rpm=in.speed_detect_rpm=20;in.iq_demand_a=.29f;tick();
    assert(fsm.state==TF_RUNDOWN);
    in.iq_demand_a=.30f;tick();assert(fsm.state==TF_CONTACT_CONFIRM&&!fsm.contact_confirmed);
    for(unsigned i=0;i<24;i++)tick();
    assert(!fsm.contact_confirmed);
    tick();assert(fsm.contact_confirmed&&fsm.intent.control_mode==CONTROL_NEUTRAL);
    arm();in.speed_ctrl_rpm=in.speed_detect_rpm=15;in.iq_demand_a=.35f;tick();
    assert(fsm.state==TF_CONTACT_CONFIRM);
    in.speed_detect_rpm=22.01f;tick();assert(fsm.state==TF_RUNDOWN&&!fsm.contact_confirmed);
    arm();in.speed_ctrl_rpm=in.speed_detect_rpm=0;in.iq_demand_a=.35f;tick();
    in.iq_demand_a=.269f;tick();assert(fsm.state==TF_RUNDOWN); /* Original30mA hysteresis. */
    arm();in.stop=1;tick();assert(fsm.state==TF_IDLE&&fsm.intent.control_mode==CONTROL_OFF);
    arm();in.protection_fault=TF_REASON_OVERCURRENT;tick();
    assert(fsm.state==TF_FAULT&&fsm.intent.control_mode==CONTROL_OFF);
}
int main(void){
    observer_checks();contact_checks();
    puts("PASS: CONTACT20 inclusive/250ms/Iq/hysteresis, observe10 signed/quality, fresh feedback20 hold/fade, STOP/fault");
    return 0;
}
