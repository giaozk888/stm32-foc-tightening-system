#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "dob_normal_control.h"

static MechanicalDobMonitor mon;
static DobFeedbackCandidate fb={.enabled=1};
static uint32_t now=1000,seq=20;
static float w=20;
static float iq(float load){
    const MechanicalNormalizedModel *m=&mechanical_dob_identified_model;
    return m->b_over_kt*w+m->coulomb_over_kt*(w>0?1.f:-1.f)+m->bias_a+load;
}
static void tick(float id,float current){
    DobNormal_Lifecycle(&mon,&fb,1,0);
    DobFeedback_Update(&fb,now+20,1000,mon.current.sample_us,mon.current.disturbance_a,
        (uint8_t)(mon.current.valid&&mon.running&&!mon.frozen),1,.5f);
    MechanicalCurrent c={2,seq,now-20,now,id,current,0};
    MechanicalDobMonitor_Observe(&mon,now+20,now,1000,w,0,&c,1);
    now+=1000;seq+=20;
}
int main(void){
    assert(DOB_FB_GAIN==.25f);
    for(int sign=-1;sign<=1;sign+=2){
        DobNormal_Lifecycle(&mon,&fb,0,0);
        assert(!fb.iq_comp_a&&!mon.current.valid);
        w=20.f*sign;
        /* A fresh entry cannot consume the previous session's valid sample. */
        DobNormal_Lifecycle(&mon,&fb,1,0);
        assert(mon.running&&!mon.current.valid&&!mon.observer.elapsed_s&&!mon.observations);
        assert(!mon.iq_lpf&&!mon.abs_id_lpf&&!fb.iq_comp_a);
        for(unsigned n=0;n<100;n++)tick(.005f,iq(.020f*sign));
        assert(!mon.current.valid&&!fb.iq_comp_a); /* Still warming, no early FF. */
        for(unsigned n=0;n<1400;n++)tick(.005f,iq(.020f*sign));
        assert(mon.current.valid&&fabsf(fb.iq_comp_a-.005f*sign)<1e-5f);
        uint32_t reset=fb.clears;float before=mon.abs_id_lpf;
        tick(.700f,iq(.020f*sign));
        assert(!mon.current.valid&&mon.abs_id_lpf==before);
        assert(!dob_current_admission.filter_updated);
        tick(.005f,iq(.020f*sign));
        for(unsigned n=0;n<15;n++)tick(.005f,iq(.020f*sign));
        assert(mon.current.valid&&fb.clears==reset);
        for(unsigned n=0;n<200;n++)tick(.080f,iq(.020f*sign));
        assert(dob_current_admission.id_bad_latched&&!mon.current.valid&&!fb.iq_comp_a);
        DobNormal_Lifecycle(&mon,&fb,0,1);
        assert(!mon.running&&!mon.current.valid&&!fb.iq_comp_a);
        DobNormal_Lifecycle(&mon,&fb,1,1);
        assert(!mon.running&&!fb.iq_comp_a); /* Fault cannot re-arm. */
        DobNormal_Lifecycle(&mon,&fb,0,0);
    }
    /* An idle OFF survives explicit speed re-entry, but observation may run. */
    fb.enabled=0;
    for(unsigned n=0;n<1500;n++)tick(.005f,iq(0));
    assert(mon.current.valid&&!fb.enabled&&!fb.iq_comp_a);
    DobNormal_Lifecycle(&mon,&fb,0,0);
    unsigned version=mon.version;
    mon.iq_lpf=42;mon.abs_id_lpf=42;
    MechanicalDobMonitor_Rearm(&mon);
    assert(mon.version==version+2&&!(mon.version&1U));
    assert(!mon.iq_lpf&&!mon.abs_id_lpf&&!mon.current.valid&&!mon.observations);
    assert(!mon.running&&!mon.frozen&&!fb.enabled);
    puts("PASS: normal DOB signed tracking, cold warmup, pre-LPF spike isolation, persistent Id, STOP/fault/OFF and versioned re-entry");
    return 0;
}
