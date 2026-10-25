#ifndef OFFLINE_LOAD_SPEED_SCHEDULER_H
#define OFFLINE_LOAD_SPEED_SCHEDULER_H
#include <math.h>
#include <stdint.h>
#include "tightening_intent_fsm.h"
/* SOFTWARE ONLY: no production caller, no reference/PI/PWM setters.
 * Input evidence is the PREVIOUS completed epoch, never future plant truth. */
typedef struct {
    uint32_t slow,high_us,release_us,last_good_us,entered_us,transitions,reason,previous_good;
} LoadSpeedScheduler;
typedef struct {
    uint32_t now_us,phase,enabled,label_valid,level,trend_valid,trend;
    float base_rpm,contact_rpm,mean_a;
} LoadSpeedEvidence;
enum { LS_BASE,LS_HIGH_CONFIRM,LS_SLOW,LS_RELEASE_CONFIRM,LS_SHORT_GAP,LS_LONG_GAP,LS_PHASE,LS_DISABLED };
static inline float LoadSpeed_Step(LoadSpeedScheduler *s,LoadSpeedEvidence e){
    float base=fabsf(e.base_rpm),sign=e.base_rpm<0?-1.f:1.f;
    if(!e.enabled||e.phase!=TF_RUNDOWN||!isfinite(e.base_rpm)){
        uint32_t changes=s->transitions;
        *s=(LoadSpeedScheduler){.transitions=changes,.reason=e.enabled?LS_PHASE:LS_DISABLED};
        return e.base_rpm;
    }
    uint32_t valid=e.label_valid&&isfinite(e.mean_a);
    if(!valid){
        s->previous_good=0;s->reason=LS_SHORT_GAP;
        if(!s->last_good_us||e.now_us-s->last_good_us>=200000U){
            if(s->slow){s->slow=0;++s->transitions;}
            s->high_us=s->release_us=0;s->reason=LS_LONG_GAP;
        }
    }else{
        uint32_t credit=s->previous_good&&e.now_us-s->last_good_us<=2000U?e.now_us-s->last_good_us:0;
        s->last_good_us=e.now_us;s->previous_good=1;
        int high=e.level==4U||(e.trend_valid&&e.trend==2U&&e.mean_a>=.010f);
        int light=e.level==1U&&(!e.trend_valid||e.trend!=2U);
        if(!s->slow){
            s->high_us=high?s->high_us+credit:0;s->release_us=0;
            s->reason=high?LS_HIGH_CONFIRM:LS_BASE;
            if(s->high_us>=30000U){s->slow=1;s->entered_us=e.now_us;++s->transitions;s->reason=LS_SLOW;}
        }else{
            s->release_us=light?s->release_us+credit:0;s->reason=light?LS_RELEASE_CONFIRM:LS_SLOW;
            if(s->release_us>=200000U&&e.now_us-s->entered_us>=300000U){
                s->slow=0;s->high_us=s->release_us=0;++s->transitions;s->reason=LS_BASE;
            }
        }
    }
    float floor=fmaxf(120.f,e.contact_rpm+12.f);
    return sign*(s->slow?fminf(base,floor):base);
}
#endif
