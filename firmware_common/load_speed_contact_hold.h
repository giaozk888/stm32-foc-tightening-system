#ifndef LOAD_SPEED_CONTACT_HOLD_H
#define LOAD_SPEED_CONTACT_HOLD_H
#include "load_speed_policy.h"
enum { LS_CONTACT_HOLD=8,LS_CONTACT_REACQUIRE=9 };
/* Candidate-only seam repair. No new slowing may start in CONTACT_CONFIRM.
 * Remember the previous selection, not a stale DOB compensation value. */
static inline float LoadSpeedContact_Step(LoadSpeedScheduler *s,uint32_t *held,
    uint32_t *reacquire,LoadSpeedEvidence e){
    if(!e.enabled||!isfinite(e.base_rpm)||e.base_rpm==0||
       (e.phase!=TF_RUNDOWN&&e.phase!=TF_CONTACT_CONFIRM)){
        *held=*reacquire=0;return LoadSpeed_Step(s,e);
    }
    if(e.phase==TF_CONTACT_CONFIRM){
        if(!s->slow){*held=*reacquire=0;return LoadSpeed_Step(s,e);}
        *held=1;*reacquire=0;s->previous_good=0;s->high_us=s->release_us=0;
        s->reason=LS_CONTACT_HOLD;
        float target=fminf(fabsf(e.base_rpm),fmaxf(120.f,e.contact_rpm+12.f));
        return e.base_rpm<0?-target:target;
    }
    uint32_t cancelled=*held;
    if(cancelled){*held=0;*reacquire=e.now_us;s->previous_good=0;s->release_us=0;}
    if(*reacquire){
        if(e.label_valid&&isfinite(e.mean_a))*reacquire=0;
        else if(e.now_us-*reacquire<200000U){
            /* No fake last-good timestamp, no missing dwell or warmup credit. */
            s->previous_good=0;s->reason=LS_CONTACT_REACQUIRE;
            float target=fminf(fabsf(e.base_rpm),fmaxf(120.f,e.contact_rpm+12.f));
            return e.base_rpm<0?-target:target;
        }else *reacquire=0;
    }
    float selected=LoadSpeed_Step(s,e);
    if(cancelled&&s->slow)s->reason=LS_CONTACT_REACQUIRE;
    return selected;
}
#endif
