#include "current_step_ab.h"
#include <math.h>
#include <limits.h>

static int32_t Abs(int32_t v){return v<0?-v:v;}
int16_t CurrentStep_TargetMa(unsigned k)
{
    static const int16_t values[CS_STEPS]={100,100,200,200,300,300,-100,-100,-200,-200};
    return k<CS_STEPS?values[k]:0;
}
unsigned CurrentStep_NewPi(unsigned k){return (k&1U)==0U;}
int CurrentStep_Queue(CurrentStepAB *s,int ready,unsigned limit_ma)
{
    if(!ready||s->used||limit_ma<CS_MAX_MA)return 0;
    s->used=1U;s->state=CS_QUEUED;return 1;
}
void CurrentStep_Begin(CurrentStepAB *s,uint32_t now)
{
    if(s->state!=CS_QUEUED)return;
    s->start_us=now;s->step=255U;s->state=CS_ACTIVE;
}
void CurrentStep_End(CurrentStepAB *s,uint8_t state,uint8_t reason)
{
    if(s->state!=CS_ACTIVE&&s->state!=CS_QUEUED)return;
    s->state=state;s->reason=reason;s->reset_pi=0;
}
int CurrentStep_PositivePass(const CurrentStepAB *s)
{
    for(unsigned k=0;k<6U;++k){
        const CurrentStepMetric *m=&s->metrics[k];
        int32_t target=(int32_t)CurrentStep_TargetMa(k)*10;
        if(m->clipped||m->baseline_n<CS_MIN_TAIL_SAMPLES||m->tail_n<CS_MIN_TAIL_SAMPLES||
           m->high_n<CS_ON_US/50U*4U/5U||m->t10_us==UINT32_MAX||
           m->t90_us==UINT32_MAX||m->t90_us<m->t10_us||m->settle_us==UINT32_MAX||
           m->settle_us>CS_ON_US-CS_STEADY_US||Abs(m->baseline)>target/20||
           s->rows[k][CS_STEADY].us%CS_SEGMENT_US-CS_PRE_US-m->settle_us<CS_STEADY_US||
           m->crossings>=CS_RING_CROSSINGS||
           m->peak>target*(100+(int32_t)CS_POS_OVERSHOOT_PERCENT)/100||
           Abs(m->tail_sum/(int32_t)m->tail_n-target)>target/20)return 0;
    }
    return 1;
}
int CurrentStep_Reference(CurrentStepAB *s,uint32_t now,int *new_pi,float *iq)
{
    *iq=0;s->reset_pi=0;
    if(s->state!=CS_ACTIVE)return 0;
    uint32_t elapsed=now-s->start_us;
    if(elapsed>=CS_MAX_US){
        if(s->step!=CS_STEPS-1U||!s->positive_pass||
           !(s->metrics[CS_STEPS-1U].valid_mask&(1U<<CS_ZERO_END))){
            CurrentStep_End(s,CS_ABORT,CS_TIME);return 0;
        }
        s->completed=CS_STEPS;CurrentStep_End(s,CS_DONE,CS_OK);return 0;
    }
    unsigned k=elapsed/CS_SEGMENT_US;
    if(k>=6U&&!s->positive_pass){
        s->completed=6U;
        if(!CurrentStep_PositivePass(s)){CurrentStep_End(s,CS_POS_QUALITY_STOP,CS_OK);return 0;}
        s->positive_pass=1U;
    }
    if(k!=s->step){
        /* A scheduling gap must not silently omit an excitation/segment. */
        if((s->step==255U&&k!=0U)||(s->step!=255U&&k!=(unsigned)s->step+1U)){
            CurrentStep_End(s,CS_ABORT,CS_TIME);return 0;
        }
        if(s->step!=255U&&!(s->metrics[s->step].valid_mask&(1U<<CS_ZERO_END))){
            CurrentStep_End(s,CS_ABORT,CS_TIME);return 0;
        }
        s->completed=(uint8_t)k;s->step=(uint8_t)k;s->reset_pi=1U;
        CurrentStepMetric *m=&s->metrics[k];
        m->t10_us=m->t90_us=m->settle_us=UINT32_MAX;m->peak=INT32_MIN;
    }
    *new_pi=(int)CurrentStep_NewPi(k);
    uint32_t local=elapsed%CS_SEGMENT_US;
    s->phase=(uint8_t)(local<CS_PRE_US?0:local<CS_PRE_US+CS_ON_US?1:2);
    if(s->phase==2U&&!s->metrics[k].high_n){
        CurrentStep_End(s,CS_ABORT,CS_BAD_DATA);return 0;
    }
    if(s->phase==1U)*iq=(float)CurrentStep_TargetMa(k)*.001f;
    s->last_us=now;return 1;
}
static int16_t Quant(float x,float scale,unsigned *clip)
{
    if(!isfinite(x)){*clip=1U;return 0;}
    float v=x*scale;
    if(v>32767.f){*clip=1U;return INT16_MAX;}
    if(v< -32768.f){*clip=1U;return INT16_MIN;}
    return (int16_t)(v+(v>=0?.5f:-.5f));
}
static void Put(CurrentStepAB *s,unsigned slot,CurrentStepFrame row)
{s->rows[s->step][slot]=row;s->metrics[s->step].valid_mask|=1U<<slot;}
void CurrentStep_Record(CurrentStepAB *s,uint32_t now,uint32_t seq,
    float iq_ref,float iq,float id,float vq,float vd,float int_q,float int_d,
    float out_q,float out_d,float omega,unsigned saturated,uint16_t fault)
{
    if(s->state!=CS_ACTIVE||s->step>=CS_STEPS)return;
    unsigned clip=0;
    CurrentStepFrame r={.us=now-s->start_us,.seq=seq,
        .iq_ref=Quant(iq_ref,10000.f,&clip),.iq=Quant(iq,10000.f,&clip),
        .id=Quant(id,10000.f,&clip),.vq=Quant(vq,10000.f,&clip),.vd=Quant(vd,10000.f,&clip),
        .int_q=Quant(int_q,10000.f,&clip),.int_d=Quant(int_d,10000.f,&clip),
        .out_q=Quant(out_q,10000.f,&clip),.out_d=Quant(out_d,10000.f,&clip),
        .omega=Quant(omega,100.f,&clip),.fault=fault};
    r.flags=(uint16_t)(1U|(CurrentStep_NewPi(s->step)<<1U)|((saturated!=0U)<<2U)|
        (clip<<3U)|((unsigned)s->phase<<4U)|((unsigned)s->step<<8U));
    CurrentStepMetric *m=&s->metrics[s->step];
    if(m->last_seq&&seq!=m->last_seq+1U){
        uint32_t delta=seq-m->last_seq;
        if(delta>100000U||!delta){CurrentStep_End(s,CS_ABORT,CS_BAD_DATA);return;}
        m->gaps+=delta-1U;
    }
    m->last_seq=seq;m->clipped|=(uint8_t)clip;
    uint32_t local=r.us%CS_SEGMENT_US;
    int32_t target=(int32_t)CurrentStep_TargetMa(s->step)*10;
    int sign=target<0?-1:1;
    if(s->phase==0U){
        if(local>=CS_PRE_US-CS_STEADY_US){m->baseline_sum+=r.iq;++m->baseline_n;}
        Put(s,CS_BASELINE,r);
    }else if(s->phase==1U){
        ++m->high_n;
        if(m->baseline_n)m->baseline=m->baseline_sum/(int32_t)m->baseline_n;
        uint32_t t=local-CS_PRE_US;
        int32_t delta=sign*((int32_t)r.iq-m->baseline),amplitude=Abs(target);
        if(m->t10_us==UINT32_MAX&&delta>=amplitude/10){m->t10_us=t;Put(s,CS_T10,r);}
        if(m->t90_us==UINT32_MAX&&delta>=amplitude*9/10){m->t90_us=t;Put(s,CS_T90,r);}
        if(sign*(int32_t)r.iq>m->peak){m->peak=sign*(int32_t)r.iq;Put(s,CS_PEAK,r);}
        int32_t error=sign*((int32_t)r.iq-target),tol=amplitude/20;
        int side=error>tol?1:error< -tol?-1:0;
        if(side){if(m->last_side&&m->last_side!=side)++m->crossings;m->last_side=(int8_t)side;m->settle_us=UINT32_MAX;}
        else if(m->settle_us==UINT32_MAX)m->settle_us=t;
        if(t>=CS_ON_US-CS_STEADY_US){m->tail_sum+=r.iq;++m->tail_n;}
        Put(s,CS_STEADY,r);
    }else Put(s,CS_ZERO_END,r);
    if(fault&&!s->failure_valid){s->failure=r;s->failure_valid=1U;CurrentStep_End(s,CS_ABORT,CS_PROTECTION);}
}
