#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "startup_timestamps.h"
static void pulse(StartupTimestamps *s,unsigned elapsed,int counts,float speed,float iq)
{
    StartupTimes_Observe(s,s->t0_us+elapsed+20U,s->t0_us+elapsed,counts,speed,iq);
}
int main(void)
{
    StartupTimestamps s;
    for (int dir=-1;dir<=1;dir+=2) {
        StartupTimes_Reset(&s);StartupTimes_Begin(&s,1000U,(float)dir*240.0f);
        StartupTimes_Begin(&s,2000U,240.0f);assert(s.t0_us==1000U);
        pulse(&s,1000,0,0,(float)dir*.009f);assert(!(s.valid&START_IQ));
        pulse(&s,2000,0,(float)dir*2.0f,(float)dir*.01f);
        assert(s.t_iq_us==3020U && s.t_speed_us==3020U && !(s.valid&START_MOTION));
        for (unsigned t=4000;t<=16000;t+=2000) pulse(&s,t,dir*4,(float)dir*3.0f,(float)dir*.1f);
        assert(s.valid==(START_T0|START_IQ|START_SPEED|START_MOTION));
        assert(s.motion_begin_us==5000U && s.t_motion_us==15000U);
        StartupTimes_Stable(&s,53000U);assert(s.valid==31U);
        unsigned ti=s.t_iq_us,tm=s.t_motion_us;
        pulse(&s,100000,dir*100,(float)dir*50.0f,(float)dir*.3f);
        StartupTimes_Stable(&s,60000U);assert(s.t_iq_us==ti && s.t_motion_us==tm && s.t_stable_us==53000U);
    }
    StartupTimes_Reset(&s);StartupTimes_Begin(&s,0U,0.0f);assert(s.valid==0U);
    StartupTimes_Begin(&s,0U,240.0f);assert(s.valid==START_T0);
    /* Noise, one spike and duplicate encoder samples cannot prove motion. */
    for (unsigned t=1000;t<=50000;t+=1000) pulse(&s,t,t%2000?1:-1,0,0);
    assert(!(s.valid&START_MOTION));
    pulse(&s,51000,100,0,0);
    for (unsigned t=52000;t<=70000;t+=1000) pulse(&s,t,0,0,0);
    assert(!(s.valid&START_MOTION));
    for (unsigned i=0;i<30;++i) pulse(&s,71000,8,0,0);
    assert(!(s.valid&START_MOTION));
    /* An early burst followed by rest must not become 'continuous' later. */
    StartupTimes_Reset(&s);StartupTimes_Begin(&s,1000U,240.0f);
    for (unsigned t=1000;t<=4000;t+=1000) pulse(&s,t,8,0,0);
    for (unsigned t=5000;t<=20000;t+=1000) pulse(&s,t,0,0,0);
    assert(!(s.valid&START_MOTION));
    /* Genuine reversal and long sample gaps restart the candidate. */
    pulse(&s,21000,8,0,0);pulse(&s,22000,-8,0,0);
    for (unsigned t=100000;t<=112000;t+=2000) pulse(&s,t,4,0,0);
    assert(s.valid&START_MOTION);assert(s.motion_begin_us==101000U);
    /* 32-bit microsecond wrap; zero timestamp is valid via valid bits. */
    StartupTimes_Reset(&s);StartupTimes_Begin(&s,0xfffff000U,240.0f);
    pulse(&s,0U,0,0,NAN);assert(!(s.valid&START_IQ));
    for (unsigned t=2000;t<=14000;t+=2000) pulse(&s,t,4,3,.02f);
    assert(s.valid&START_MOTION);assert((unsigned)(s.t_motion_us-s.t0_us)==12000U);
    StartupTimes_Reset(&s);assert(s.valid==0U && s.observations==0U);
    StartupTimes_Begin(&s,1000U,240.0f);
    for (unsigned t=2000;t<=14000;t+=2000) pulse(&s,t,-4,-3.0f,.02f);
    assert(s.valid&START_MOTION);assert(s.valid&START_SPEED);
    assert(s.motion_direction==-1 && s.speed_at_event_rpm==-3.0f);
    assert(!(s.valid&START_STABLE)); /* Existing directional stable guard remains separate. */
    puts("PASS: five independent events, noise/rest/reversal/gaps/wrap/reset, no control writes");
    return 0;
}
