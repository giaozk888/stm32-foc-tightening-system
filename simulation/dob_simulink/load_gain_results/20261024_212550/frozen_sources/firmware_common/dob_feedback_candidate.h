#ifndef DOB_FEEDBACK_CANDIDATE_H
#define DOB_FEEDBACK_CANDIDATE_H
#include <math.h>
#include <stdint.h>
#include "speed_friction_compensation.h"
/* Application A bounded adapter (diagnostic or selected normal DOB profile).
 * Estimator positive residual is resisting load current:
 * J/Kt*dw = Iq - friction - bias - d_load; compensation therefore adds +d.
 * No observer, FOC feedback, PI tuning, safety or persistent parameter writes. */
#ifndef DOB_FB_GAIN
#define DOB_FB_GAIN .25f
#endif
#define DOB_FB_LIMIT_A .025f
#define DOB_FB_LIMIT_FRACTION .05f
#define DOB_FB_SLEW_A_S .25f
#define DOB_FB_FRESH_US 2000U
#define DOB_FB_HOLD_US 5000U
#define DOB_FB_ZERO_US 20000U
enum { DOB_FB_OFF,DOB_FB_WAIT,DOB_FB_TRACK,DOB_FB_HOLD,DOB_FB_FADE,DOB_FB_EXPIRED };
typedef struct {
    float iq_comp_a,disturbance_a,peak_a,iq_pi_a,iq_raw_a,iq_ref_a,integral_a;
    uint32_t enabled,have_valid,last_valid_us,age_us,sample_us,state;
    uint32_t updates,valid_updates,holds,fades,clears,clamps,saturation;
} DobFeedbackCandidate;
_Static_assert(sizeof(DobFeedbackCandidate)==80U,"DOB feedback A RAM budget");
static inline float DobFb_Clamp(float x,float limit){
    return x < -limit ? -limit : x > limit ? limit : x;
}
static inline float DobFb_Move(float x,float target,float step){
    return x<target ? fminf(x+step,target) : fmaxf(x-step,target);
}
static inline void DobFeedback_Clear(DobFeedbackCandidate *s){
    if(s->have_valid||s->iq_comp_a!=0)++s->clears;
    s->iq_comp_a=0;s->disturbance_a=0;s->have_valid=0;s->age_us=0;
    s->state=s->enabled?DOB_FB_WAIT:DOB_FB_OFF;
}
static inline float DobFeedback_Update(DobFeedbackCandidate *s,uint32_t now,uint32_t dt,
    uint32_t source_us,float estimate,uint8_t valid,uint8_t running,float iq_limit){
    ++s->updates;s->sample_us=now;
    if(!s->enabled||!running||!dt||dt>DOB_FB_FRESH_US||
       !isfinite(iq_limit)||iq_limit<=0){DobFeedback_Clear(s);return 0;}
    float cap=fminf(DOB_FB_LIMIT_A,DOB_FB_LIMIT_FRACTION*iq_limit);
    s->iq_comp_a=DobFb_Clamp(s->iq_comp_a,cap);
    if(valid&&isfinite(estimate)&&now-source_us<=DOB_FB_FRESH_US){
        s->have_valid=1;s->last_valid_us=source_us;s->age_us=now-source_us;
        s->disturbance_a=estimate;s->state=DOB_FB_TRACK;++s->valid_updates;
        float raw=DOB_FB_GAIN*estimate,target=DobFb_Clamp(raw,cap);
        if(raw!=target)++s->clamps;
        s->iq_comp_a=DobFb_Move(s->iq_comp_a,target,DOB_FB_SLEW_A_S*(float)dt*1e-6f);
    }else if(s->have_valid){
        s->age_us=now-s->last_valid_us;
        if(s->age_us<=DOB_FB_HOLD_US){s->state=DOB_FB_HOLD;++s->holds;}
        else if(s->age_us<DOB_FB_ZERO_US){
            s->state=DOB_FB_FADE;++s->fades;
            float step=cap*(float)dt/(float)(DOB_FB_ZERO_US-DOB_FB_HOLD_US);
            s->iq_comp_a=DobFb_Move(s->iq_comp_a,0,step);
        }else{
            s->iq_comp_a=0;s->have_valid=0;s->state=DOB_FB_EXPIRED;
        }
    }else{s->iq_comp_a=0;s->state=DOB_FB_WAIT;}
    s->peak_a=fmaxf(s->peak_a,fabsf(s->iq_comp_a));return s->iq_comp_a;
}
/* OFF uses the original function exactly. ON uses the same conditional/partial
 * integration rule, but its saturation boundary includes ALL feedforward.
 * Never clamp PI first then add DOB outside the actuator limit. */
static inline SpeedFrictionResult SpeedFrictionDob_Apply(float previous,float candidate,float p,
    float accel_ref,float ka,float speed_ref,float friction_a,float deadband,
    float iq_limit,float integral_limit,uint8_t release,uint8_t accel_enabled,uint8_t enabled,
    float dob_a){
    if(!isfinite(dob_a)||dob_a==0)return SpeedFriction_Apply(previous,candidate,p,
        accel_ref,ka,speed_ref,friction_a,deadband,iq_limit,integral_limit,release,accel_enabled,enabled);
    float fric=enabled&&fabsf(speed_ref)>deadband?(speed_ref>0?friction_a:-friction_a):0;
    float acc=accel_enabled?ka*accel_ref:0;
    previous=DobFb_Clamp(previous,integral_limit);candidate=DobFb_Clamp(candidate,integral_limit);
    float raw=(((p+candidate)+acc)+fric)+dob_a,ref=DobFb_Clamp(raw,iq_limit),admitted=candidate;
    if(!release){
        if(candidate>previous&&raw>ref){
            float boundary=(((iq_limit-dob_a)-fric)-acc)-p;
            admitted=boundary>previous?fminf(candidate,boundary):previous;
        }else if(candidate<previous&&raw<ref){
            float boundary=(((-iq_limit-dob_a)-fric)-acc)-p;
            admitted=boundary<previous?fmaxf(candidate,boundary):previous;
        }
    }
    uint8_t limited=(uint8_t)(admitted!=candidate);float pi=p+admitted;
    raw=((pi+acc)+fric)+dob_a;ref=DobFb_Clamp(raw,iq_limit);
    return (SpeedFrictionResult){{admitted,pi,acc,raw,ref,
        (uint8_t)(raw!=ref||fabsf(ref)>=iq_limit||limited),limited},fric};
}
#endif
