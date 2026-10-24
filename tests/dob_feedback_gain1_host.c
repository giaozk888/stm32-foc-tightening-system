#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "dob_feedback_candidate.h"
#ifndef EXPECTED_DOB_FB_GAIN
#define EXPECTED_DOB_FB_GAIN 1.0f
#endif
static float update(DobFeedbackCandidate *s,unsigned now,float d,unsigned valid){
    return DobFeedback_Update(s,now,1000,now-1000,d,(uint8_t)valid,1,.5f);
}
int main(void){
    assert(DOB_FB_GAIN==EXPECTED_DOB_FB_GAIN&&DOB_FB_LIMIT_A==.025f&&DOB_FB_LIMIT_FRACTION==.05f);
    assert(DOB_FB_SLEW_A_S==.25f&&DOB_FB_HOLD_US==5000&&DOB_FB_ZERO_US==20000);
    DobFeedbackCandidate s={0};assert(update(&s,1000,.02f,1)==0);
    for(unsigned sign=0;sign<2;sign++){
        s=(DobFeedbackCandidate){.enabled=1};float d=sign?-.020f:.020f,prev=0;
        for(unsigned t=1000;t<=100000;t+=1000){float c=update(&s,t,d,1);
            assert(fabsf(c-prev)<=.00025001f&&fabsf(c)<=.025f);prev=c;}
        assert(fabsf(s.iq_comp_a-DOB_FB_GAIN*d)<1e-7f);
        unsigned good=s.last_valid_us;
        for(unsigned t=101000;t<=good+5000;t+=1000)assert(update(&s,t,NAN,0)==prev);
        for(unsigned t=good+6000;t<=good+20000;t+=1000){float c=update(&s,t,NAN,0);
            assert(fabsf(c)<=fabsf(prev));prev=c;}
        assert(!s.iq_comp_a&&!s.have_valid);
        assert(fabsf(update(&s,150000,d,1))<=.00025001f);
    }
    for(unsigned t=151000;t<=300000;t+=1000)update(&s,t,1,1);
    assert(s.iq_comp_a==.025f&&s.clamps);
    assert(DobFeedback_Update(&s,301000,1000,300000,1,1,1,.10f)<=.00500001f);
    assert(DobFeedback_Update(&s,302000,1000,301000,1,1,0,.5f)==0);
    /* ON sum/AW stays total-output bounded, regardless of observer gain. */
    for(unsigned sign=0;sign<2;sign++){
        float k=sign?-1.f:1.f;
        SpeedFrictionResult r=SpeedFrictionDob_Apply(k*.1f,k*.2f,k*.28f,0,0,k*600,0,2,.5f,.5f,0,0,0,k*.025f);
        assert(r.speed.aw_limited&&fabsf(r.speed.iq_ref_a)<=.5f);
    }
    printf("PASS: gain%.3g scaled +/-20mA tracking, 25mA cap, unchanged slew/gaps/total-AW, defaultOFF and STOP\n",(double)DOB_FB_GAIN);
    return 0;
}
