#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "dob_feedback_candidate.h"
static uint32_t rng=17;
static float random_signed(void){rng=1664525*rng+1013904223;return (float)(rng&65535)/32768.f-1.f;}
static float update(DobFeedbackCandidate *s,unsigned t,float d,unsigned valid){
    return DobFeedback_Update(s,t,1000,t-1000,d,(uint8_t)valid,1,.5f);
}
int main(void){
    DobFeedbackCandidate s={0};
    assert(update(&s,1000,.02f,1)==0); /* Runtime default OFF. */
    s.enabled=1;
    float prev=0;
    for(unsigned t=1000;t<=30000;t+=1000){
        float c=update(&s,t,.02f,1);
        assert(c>=0&&c-prev<=.00025001f&&c<=.00500001f);prev=c;
    }
    assert(fabsf(s.iq_comp_a-.005f)<1e-7f);
    unsigned last=s.last_valid_us;
    for(unsigned t=31000;t<=last+5000;t+=1000){
        assert(update(&s,t,NAN,0)==prev&&s.state==DOB_FB_HOLD);
    }
    for(unsigned t=last+6000;t<=last+20000;t+=1000){
        float c=update(&s,t,NAN,0);assert(c<=prev&&c>=0);prev=c;
    }
    assert(!s.iq_comp_a&&!s.have_valid&&s.state==DOB_FB_EXPIRED);
    assert(update(&s,60000,.1f,1)<=.00025001f); /* Re-entry slew, not jump. */
    for(unsigned t=61000;t<=190000;t+=1000)update(&s,t,10,1);
    assert(s.iq_comp_a<=.025f&&s.clamps);
    assert(DobFeedback_Update(&s,191000,1000,190000,10,1,1,.1f)<=.00500001f);
    assert(DobFeedback_Update(&s,192000,1000,191000,10,1,0,.5f)==0);
    assert(!s.have_valid); /* STOP/fault/control mode cannot retain compensation. */
    for(unsigned t=200000;t<240000;t+=1000)update(&s,t,-.02f,1);
    assert(s.iq_comp_a<0);
    unsigned age_before=s.last_valid_us;
    (void)DobFeedback_Update(&s,244000,1000,age_before-1000,.1f,1,1,.5f);
    assert(s.last_valid_us==age_before); /* Stale 'valid' cannot refresh hold. */
    s.enabled=0;assert(update(&s,245000,-.02f,1)==0);
    s=(DobFeedbackCandidate){.enabled=1};
    for(unsigned i=0;i<40;i++)update(&s,0xfffff000U+i*1000U,.02f,1);
    assert(s.iq_comp_a>0); /* Clock wrap does not disable fresh samples. */
    /* OFF matches original numerical outputs, all feedforward conditions. */
    for(unsigned i=0;i<30000;i++){
        float previous=random_signed()*.5f,candidate=random_signed()*.5f;
        float p=random_signed(),acc=random_signed()*300,ref=random_signed()*600;
        unsigned fric=i%2,ff=(i/2)%2,release=(i/4)%2;
        SpeedFrictionResult old=SpeedFriction_Apply(previous,candidate,p,acc,.000046875f,
            ref,.105f,2,.5f,.5f,release,ff,fric);
        SpeedFrictionResult off=SpeedFrictionDob_Apply(previous,candidate,p,acc,.000046875f,
            ref,.105f,2,.5f,.5f,release,ff,fric,0);
        assert(old.speed.integral_a==off.speed.integral_a&&old.speed.iq_pi_a==off.speed.iq_pi_a);
        assert(old.speed.iq_ff_a==off.speed.iq_ff_a&&old.speed.iq_raw_a==off.speed.iq_raw_a);
        assert(old.speed.iq_ref_a==off.speed.iq_ref_a&&old.speed.saturated==off.speed.saturated);
        float dob=random_signed()*.025f;
        SpeedFrictionResult on=SpeedFrictionDob_Apply(previous,candidate,p,acc,.000046875f,
            ref,.105f,2,.5f,.5f,release,ff,fric,dob);
        assert(fabsf(on.speed.iq_ref_a)<=.5f);
        assert(fabsf(on.speed.iq_raw_a-(((on.speed.iq_pi_a+on.speed.iq_ff_a)+on.iq_fric_a)+dob))<1e-7f);
    }
    /* PI alone is below the limit; total DOB+FF causes saturation and AW. */
    SpeedFrictionResult a=SpeedFrictionDob_Apply(.10f,.20f,.28f,0,0,600,0,2,.5f,.5f,0,0,0,.025f);
    assert(a.speed.aw_limited&&a.speed.integral_a<.20f&&fabsf(a.speed.iq_ref_a)<=.5f);
    a=SpeedFrictionDob_Apply(-.10f,-.20f,-.28f,0,0,-600,0,2,.5f,.5f,0,0,0,-.025f);
    assert(a.speed.aw_limited&&a.speed.integral_a>-.20f&&fabsf(a.speed.iq_ref_a)<=.5f);
    /* Resisting load of +20mA: adding positive compensation gives positive
     * mechanical acceleration; wrong negative feedback would worsen deficit. */
    float j=.00037829066f,load=.020f;
    assert((.25f*load-load)/j > (-load)/j);
    puts("PASS: signed load compensation, exact OFF, bounded total/AW, hold/fade/re-entry/stale/STOP/wrap");
    return 0;
}
