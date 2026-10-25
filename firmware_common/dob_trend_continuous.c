#include "dob_trend_continuous.h"
#include <math.h>
DobTrendContinuous dob_trend_continuous;
DobTrendContinuousArena *dob_trend_continuous_arena;
static void event(uint32_t now,uint16_t type){
    DobTrendContinuous *h=&dob_trend_continuous;
    DobTrendClassifier *s=&dob_trend_continuous_arena->classifier;
    type|=(uint16_t)(s->valid?256U:0U)|(uint16_t)(s->trend_valid?512U:0U);
    dob_trend_continuous_arena->events[h->event_head]=(DobTrendEvent){now,type,(uint8_t)s->state,(uint8_t)s->trend_state};
    h->event_head=(h->event_head+1U)%DTC_EVENTS;
    if(++h->event_count>DTC_EVENTS){++h->event_dropped;h->flags|=DTC_EVENT_WRAP;}
}
void DobTrendContinuous_Bind(void *buffer,size_t bytes){
    if(dob_trend_continuous_arena||dob_trend_continuous.abi)return;
    dob_trend_continuous.abi=2;
    if(!buffer||bytes<sizeof(DobTrendContinuousArena)||((uintptr_t)buffer&3U)){
        dob_trend_continuous.flags=DTS_BUFFER_ERROR;return;
    }
    dob_trend_continuous_arena=(DobTrendContinuousArena *)buffer;
    DobTrendClassifier_Reset(&dob_trend_continuous_arena->classifier);
    dob_trend_continuous.dt_min_us=UINT32_MAX;
}
static int16_t quantize(float value,float scale){
    if(!isfinite(value)){dob_trend_continuous.flags|=DTC_LOG_NONFINITE;return 0;}
    value*=scale;
    if(value>32767.f)value=32767.f;
    if(value< -32767.f)value= -32767.f;
    return (int16_t)(value+(value>=0?.5f:-.5f));
}
void DobTrendContinuous_Observe(DobTrendInput in,float ref,float accel,float rpm,float iq,uint32_t status){
    if(!dob_trend_continuous_arena)return;
    DobTrendContinuous *h=&dob_trend_continuous;
    DobTrendClassifier *s=&dob_trend_continuous_arena->classifier;
    if(!in.running){
        if(h->observations&&!(h->flags&DTS_STOPPED)){
            h->flags|=DTS_DONE|DTS_STOPPED;event(in.encoder_us,DTC_STOP);
        }
        return;
    }
    if(h->flags&DTS_STOPPED)return; /* One explicitly supervised session only. */
    if(!h->observations)h->start_us=in.encoder_us;
    uint32_t dt=s->have_call?in.encoder_us-s->last_call:1000U;
    uint32_t old_trend=s->trend_state,old_level=s->state,old_resets=s->resets;
    ++h->observations;if(dt<h->dt_min_us)h->dt_min_us=dt;if(dt>h->dt_max_us)h->dt_max_us=dt;
    /* Never gated by ring counts, first trigger, record wrap or event wrap. */
    DobTrendClassifier_Step(s,in);h->feature_updates+=s->updated;
    if(s->resets!=old_resets)event(in.encoder_us,DTC_RESET);
    if(s->state!=old_level)event(in.encoder_us,DTC_LEVEL);
    if(s->trend_state!=old_trend)event(in.encoder_us,DTC_TREND);
    if(!(h->flags&DTS_ARMED)){
        if(in.encoder_us-h->start_us>=2000000U&&s->valid&&fabsf(ref)>=235&&fabsf(ref)<=245&&
           fabsf(accel)<.001f&&fabsf(rpm-ref)<=5)h->arm_qual_us+=dt;
        else h->arm_qual_us=0;
        if(h->arm_qual_us>=40000U){
            h->flags|=DTS_ARMED;h->arm_us=in.encoder_us;h->baseline_a=h->peak_a=s->mean;
            event(in.encoder_us,DTC_ARM);
        }
    }
    if((h->flags&DTS_ARMED)&&s->valid){
        uint32_t above=(uint32_t)(s->mean-h->baseline_a>=.010f);
        if(above!=h->proxy_above){
            h->proxy_above=above;event(in.encoder_us,above?DTC_MEAN_UP:DTC_MEAN_DOWN);
        }
        if(!(h->flags&DTS_TRIGGERED)&&above){
            h->flags|=DTS_TRIGGERED;h->proxy_rise_us=in.encoder_us;
            if(old_trend==DTS_RISING)h->flags|=DTS_PREACTIVE_RISE;
        }
        if(s->mean>h->peak_a)h->peak_a=s->mean;
        if((h->flags&DTS_TRIGGERED)&&!h->proxy_fall_us&&h->peak_a-s->mean>=.010f){
            h->proxy_fall_us=in.encoder_us;if(old_trend==DTS_FALLING)h->flags|=DTS_PREACTIVE_FALL;
        }
    }
    if(h->flags&DTS_TRIGGERED){
        if(!h->trend_rise_us&&s->trend_valid&&s->trend_state==DTS_RISING&&old_trend!=DTS_RISING)h->trend_rise_us=in.encoder_us;
        if(h->proxy_fall_us&&!h->trend_fall_us&&s->trend_valid&&s->trend_state==DTS_FALLING&&old_trend!=DTS_FALLING)h->trend_fall_us=in.encoder_us;
        if(!h->level_high_us&&s->valid&&s->state==DTS_HIGH)h->level_high_us=in.encoder_us;
    }
    if(h->record_count&&in.encoder_us-h->last_record_us<DTC_RECORD_US)return;
    uint16_t flags=(uint16_t)(status&2047U);
    flags|=(uint16_t)(in.valid?2048U:0U)|(uint16_t)(in.filter_updated?4096U:0U)|
        (uint16_t)(s->valid?8192U:0U)|(uint16_t)(s->trend_valid?16384U:0U);
    if(h->flags&DTS_TRIGGERED)flags|=32768U;
    dob_trend_continuous_arena->points[h->head]=(DobTrendContinuousPoint){in.encoder_us,
        isfinite(in.disturbance_a)?in.disturbance_a:0,s->mean,s->trend_filtered,
        quantize(rpm,10.f),quantize(iq,1000.f),flags,(uint8_t)s->state,(uint8_t)s->trend_state};
    h->head=(h->head+1U)%DTC_POINTS;h->last_record_us=in.encoder_us;
    if(++h->record_count>DTC_POINTS){++h->record_overflow;h->flags|=DTC_RECORD_WRAP;}
    /* Ring wrap only overwrites old telemetry. No classifier/DOB reset. */
}
