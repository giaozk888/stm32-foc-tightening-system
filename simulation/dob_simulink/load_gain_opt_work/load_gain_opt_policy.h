#ifndef OFFLINE_LOAD_GAIN_OPT_POLICY_H
#define OFFLINE_LOAD_GAIN_OPT_POLICY_H
#include <math.h>
#include <stdint.h>
/* SOFTWARE ONLY. Dimensionless gain; no Iq, observer, PI, FSM or PWM writes.
 * Evidence is the previous completed causal classifier / observer snapshot. */
enum { LG_FIXED,LG_OFF,LG_INACTIVE,LG_WAIT,LG_HIGH_CONFIRM,LG_LOADED,
       LG_RELEASE_CONFIRM,LG_SHORT_GAP,LG_FADE,LG_LONG_GAP };
typedef struct {
    float selected,requested;
    uint32_t active,high_us,release_us,last_good_us,last_step_us,entered_us;
    uint32_t previous_good,have_step,reason,updates,transitions,credit_us;
} LoadGainScheduler;
typedef struct {
    uint32_t now_us,phase,running,fault,feedback_enabled,adaptive,valid;
    uint32_t level,trend_valid,trend;
    float mean_a,max_gain;
} LoadGainEvidence;
static inline float LoadGain_Move(float a,float b,float step){
    return a<b?fminf(a+step,b):fmaxf(a-step,b);
}
static inline float LoadGainOpt_Step(LoadGainScheduler *s,LoadGainEvidence e,uint32_t profile){
    uint32_t dt=s->have_step?e.now_us-s->last_step_us:0;
    if(s->have_step && !dt)return s->selected;
    s->have_step=1;s->last_step_us=e.now_us;++s->updates;s->credit_us=0;
    float cap=isfinite(e.max_gain)?fminf(.25f,fmaxf(0,e.max_gain)):0;
    float floor=fminf(cap,(profile==3U||profile==4U)?.10f:0.f);
    float rise=(profile==2U||profile==4U)?5.f:1.f;
    if(!e.feedback_enabled||!cap){
        s->selected=s->requested=0;s->active=s->previous_good=s->high_us=s->release_us=0;s->reason=LG_OFF;return 0;
    }
    if(!e.adaptive){s->requested=s->selected=cap;s->reason=LG_FIXED;return cap;}
    if(!e.running||e.fault||e.phase!=3U){
        s->selected=s->requested=0;s->active=s->previous_good=s->high_us=s->release_us=0;s->reason=LG_INACTIVE;return 0;
    }
    uint32_t valid=e.valid&&isfinite(e.mean_a),credit=0;
    if(valid){
        credit=s->previous_good&&e.now_us-s->last_good_us<=2000U?e.now_us-s->last_good_us:0;
        s->last_good_us=e.now_us;s->previous_good=1;s->credit_us=credit;
        uint32_t high=(e.level==4U&&e.mean_a>=.025f)||(e.trend_valid&&e.trend==2U&&e.mean_a>=.010f);
        uint32_t light=e.level==1U&&(!e.trend_valid||e.trend!=2U);
        if(!s->active){
            s->high_us=high?s->high_us+credit:0;s->release_us=0;s->reason=high?LG_HIGH_CONFIRM:LG_WAIT;
            if(s->high_us>=30000U){s->active=1;s->entered_us=e.now_us;++s->transitions;s->reason=LG_LOADED;}
        }else{
            s->release_us=light?s->release_us+credit:0;s->reason=light?LG_RELEASE_CONFIRM:LG_LOADED;
            if(s->release_us>=200000U&&e.now_us-s->entered_us>=300000U){
                s->active=0;s->high_us=s->release_us=0;++s->transitions;s->reason=LG_WAIT;
            }
        }
        s->requested=s->active?cap:floor;
    }else{
        s->previous_good=0;s->reason=LG_SHORT_GAP;
        uint32_t age=s->last_good_us?e.now_us-s->last_good_us:UINT32_MAX;
        if(age>5000U){s->requested=0;s->reason=LG_FADE;}
        if(age>=200000U){
            if(s->active)++s->transitions;
            s->active=s->high_us=s->release_us=0;s->reason=LG_LONG_GAP;
        }
    }
    /* Missing wall time earns neither dwell nor a large catch-up gain step. */
    if(dt && dt<=2000U && (valid||s->reason!=LG_SHORT_GAP)){
        float slew=s->requested>s->selected?rise:2.5f;
        s->selected=LoadGain_Move(s->selected,s->requested,slew*(float)dt*1e-6f);
    }
    s->selected=fminf(cap,fmaxf(0,s->selected));return s->selected;
}
#endif
