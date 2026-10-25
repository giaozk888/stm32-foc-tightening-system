#include "dob_load_speed_candidate.h"
#include "dob_trend_continuous.h"
#include <string.h>
#if !defined(FOC_DOB_TREND_WINDOW75) || !defined(FOC_DOB_TREND_CONTINUOUS)
#error Load speed candidate requires exclusive window75 recorder
#endif
DobLoadSpeed dob_load_speed;
static void save_event(DobTrendClassifier *c,uint32_t n,const DobLoadSpeedEvent *e){
    uint32_t offset=8U+(n?1U+(n-1U)%2U:0U)*64U,left=64U;
    const unsigned char *p=(const unsigned char *)e;
    while(left){
        unsigned char *dest=offset<100U?(unsigned char *)&c->value[75]+offset:
            (unsigned char *)&c->stamp[75]+offset-100U;
        uint32_t count=offset<100U?100U-offset:200U-offset;if(count>left)count=left;
        memcpy(dest,p,count);p+=count;offset+=count;left-=count;
    }
}
float DobLoadSpeed_Select(uint32_t now,uint32_t phase,float base,float contact,float ref,float accel){
    DobLoadSpeed *s=&dob_load_speed;
    /* The sole writer is the existing1kHz task, prior to the S-curve.
     * Classifier was completed by the previous acknowledged task epoch. */
    if(s->samples&&now==s->last_epoch_us)return s->selected_rpm;
    DobTrendClassifier *c=dob_trend_continuous_arena?&dob_trend_continuous_arena->classifier:0;
    uint32_t valid=c&&c->valid&&now-c->last_call<=2000U;
    uint32_t from=s->policy.slow;
    LoadSpeedEvidence in={now,phase,1U,valid,c?c->state:0,c?c->trend_valid:0,c?c->trend_state:0,
        base,contact,c?c->mean:0};
    float selected=LoadSpeed_Step(&s->policy,in);
    s->last_epoch_us=now;++s->samples;s->slow_epochs+=s->policy.slow;s->invalid_epochs+=!valid;
    s->base_rpm=base;s->selected_rpm=selected;s->phase=phase;
    if(c&&from!=s->policy.slow){
        uint32_t n;memcpy(&n,&c->value[76],4);
        DobLoadSpeedEvent e={now,s->policy.reason,phase,from,s->policy.slow,valid,in.level,in.trend_valid,in.trend,
            s->policy.high_us,s->policy.release_us,base,selected,in.mean_a,ref,accel};
        save_event(c,n,&e);
        uint32_t header[2]={0xD1500001U,n+1U};memcpy(&c->value[75],header,8);
    }
    return selected;
}
