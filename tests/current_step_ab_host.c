#include "current_step_ab.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#undef assert
#define assert(x) do {if(!(x)){fprintf(stderr,"CHECK %d: %s\n",__LINE__,#x);exit(2);}} while(0)

static void tick(CurrentStepAB *s,uint32_t elapsed,int bad)
{
    float ref;int pi;
    if(!CurrentStep_Reference(s,s->start_us+elapsed,&pi,&ref))return;
    assert(pi==(int)CurrentStep_NewPi(s->step));
    assert(s->phase==1U || ref==0.f);
    assert(fabsf(ref)<=.300001f);
    uint32_t local=elapsed%CS_SEGMENT_US;
    float iq=0.f;
    if(s->phase==1U){
        float t=(float)(local-CS_PRE_US+50U);
        iq=ref*(1.f-expf(-t/1000.f));
        if(bad==1)iq=0.f;
        if(bad==2)iq=ref*1.3f;
        if(bad==3 && local>CS_PRE_US+5000U && local<CS_PRE_US+12000U)
            iq=ref*((local/500U)&1U?1.1f:.9f);
    }
    CurrentStep_Record(s,s->start_us+elapsed,elapsed/50U+1U,ref,iq,0.f,
        .1f,0.f,.01f,0.f,.1f,0.f,0.f,0U,0U);
}
static CurrentStepAB fresh(void)
{
    CurrentStepAB s={0};
    assert(!CurrentStep_Queue(&s,0,500));assert(!CurrentStep_Queue(&s,1,299));
    assert(CurrentStep_Queue(&s,1,500));CurrentStep_Begin(&s,12345U);
    return s;
}
int main(void)
{
    assert(sizeof(CurrentStepFrame)==32U);assert(sizeof(CurrentStepMetric)==60U);
    assert(sizeof(CurrentStepAB)==2576U);
    CurrentStepAB s=fresh();unsigned resets=0;
    for(uint32_t t=0;t<=CS_MAX_US;t+=50U){tick(&s,t,0);resets+=s.reset_pi;}
    assert(s.state==CS_DONE&&s.completed==10U&&s.positive_pass&&resets==10U);
    assert(CurrentStep_PositivePass(&s));
    for(unsigned k=0;k<CS_STEPS;++k){
        assert(s.metrics[k].baseline_n==100U&&s.metrics[k].high_n==600U);
        assert(s.metrics[k].tail_n==100U&&s.metrics[k].valid_mask==63U);
        assert(s.metrics[k].t10_us>=50U&&s.metrics[k].t10_us<=100U);
        assert(s.metrics[k].t90_us>=2250U&&s.metrics[k].t90_us<=2300U);
        assert(s.rows[k][CS_ZERO_END].iq_ref==0);
    }
    assert(!CurrentStep_Queue(&s,1,500));
    CurrentStepAB before=s;CurrentStep_End(&s,CS_ABORT,CS_PROTECTION);
    assert(!memcmp(&before,&s,sizeof s));
    for(int bad=1;bad<=3;++bad){
        s=fresh();
        for(uint32_t t=0;t<=6U*CS_SEGMENT_US;t+=50U)tick(&s,t,bad);
        assert(s.state==CS_POS_QUALITY_STOP&&s.completed==6U&&!s.positive_pass);
        assert(!s.metrics[6].high_n);assert(!CurrentStep_Queue(&s,1,500));
    }
    s=fresh();tick(&s,0,0);tick(&s,CS_MAX_US,0);
    assert(s.state==CS_ABORT&&s.reason==CS_TIME); /* cannot skip the batch */
    s=fresh();tick(&s,0,0);tick(&s,CS_PRE_US+CS_ON_US,0);
    assert(s.state==CS_ABORT&&s.reason==CS_BAD_DATA); /* no accepted excitation */
    s=fresh();tick(&s,0,0);
    CurrentStep_Record(&s,s.start_us+50U,2U,0,0,0,0,0,0,0,0,0,0,0,7U);
    assert(s.state==CS_ABORT&&s.failure_valid&&s.failure.fault==7U);
    before=s;tick(&s,50000U,0);assert(!memcmp(&before,&s,sizeof s));
    s=fresh();CurrentStep_End(&s,CS_ABORT,CS_CANCELLED);
    assert(!CurrentStep_Queue(&s,1,500)); /* no auto-retry */
    s=fresh();s.start_us=UINT32_MAX-10000U;
    for(uint32_t t=0;t<=CS_MAX_US;t+=50U)tick(&s,t,0);
    assert(s.state==CS_DONE); /* timestamp wrap */
    puts("PASS current step AB: one batch, gates, refs, metrics, fault/cancel, wrap");
    return 0;
}
