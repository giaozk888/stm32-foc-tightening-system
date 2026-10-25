#include "dob_trend_shadow.h"
#include <math.h>
#include <string.h>
DobTrendShadow dob_trend_shadow;
DobTrendArena *dob_trend_arena;
void DobTrendClassifier_Reset(DobTrendClassifier *s){memset(s,0,sizeof *s);}
static void clear(DobTrendClassifier *s){
    memset(s->good,0,sizeof s->good);s->head=s->count=s->state=s->proposal=0;
    s->mean=s->trend=s->coverage=s->trend_filtered=0;
    s->level_dwell_us=s->trend_dwell_us=s->trend_state=s->trend_proposal=0;
    s->previous_good=s->have_source=0;++s->resets;
}
void DobTrendClassifier_Step(DobTrendClassifier *s,DobTrendInput in){
    uint32_t dt=s->have_call?in.encoder_us-s->last_call:1000U;
    s->valid=s->trend_valid=s->updated=0;s->reason=0;
    if(in.fault)s->reason=3;
    else if(!in.running)s->reason=2;
    else if(dt<500U||dt>2000U)s->reason=10;
    else if(in.direction!=1&&in.direction!=-1)s->reason=9;
    if(s->reason){if(s->count||s->state||s->have_source)clear(s);s->direction=in.direction;}
    else{
        if(s->direction&&s->direction!=in.direction){clear(s);s->reason=9;}
        s->direction=in.direction;
        int good=in.valid&&in.filter_updated&&isfinite(in.disturbance_a)&&
            in.observed_us-in.source_us<=2000U&&
            (!s->have_source||(int32_t)(in.source_us-s->last_source)>0);
        if(s->have_source&&in.encoder_us-s->last_good>=20000U){clear(s);s->reason=6;}
        uint32_t slot=s->head;s->head=(slot+1U)%DTS_WINDOW;
        if(s->count<DTS_WINDOW)++s->count;
        s->good[slot]=(uint8_t)good;s->stamp[slot]=in.encoder_us;
        if(good){
            s->value[slot]=(float)in.direction*in.disturbance_a;
            s->last_source=in.source_us;s->last_good=in.encoder_us;s->have_source=1;++s->accepted;
        }else{++s->rejected;s->previous_good=0;if(s->reason!=6)s->reason=s->have_source?5:4;}
        float sx=0,sy=0,sxx=0,sxy=0;uint32_t n=0,span=0;
        for(uint32_t k=0;k<DTS_WINDOW;++k){
            if(!s->good[k])continue;
            uint32_t age=in.encoder_us-s->stamp[k];float x=-(float)age*1e-6f;
            ++n;sx+=x;sy+=s->value[k];sxx+=x*x;sxy+=x*s->value[k];if(age>span)span=age;
        }
        s->coverage=(float)n*(1.f/(float)DTS_WINDOW);
        if(good){
            if(span<DOB_WINDOW_MIN_SPAN_US){s->reason=7;s->level_dwell_us=0;}
            else if(n<DOB_WINDOW_MIN_GOOD){s->reason=8;s->level_dwell_us=0;}
            else{
                float den=(float)n*sxx-sx*sx;
                s->mean=sy/(float)n;s->trend=den>1e-12f?((float)n*sxy-sx*sy)/den:0;s->updated=1;
                uint32_t level=DTS_MEDIUM;
                if(s->mean>=.025f||(s->state==DTS_HIGH&&s->mean>=.020f))level=DTS_HIGH;
                else if(s->mean<=.010f||(s->state==DTS_LIGHT&&s->mean<=.015f))level=DTS_LIGHT;
                if(level!=s->proposal){s->proposal=level;s->level_dwell_us=0;}
                else if(s->previous_good)s->level_dwell_us+=dt;
                if(s->level_dwell_us>=30000U&&s->state!=level){s->state=level;++s->level_changes;}
                s->trend_filtered+=(float)dt/(100000.f+(float)dt)*(s->trend-s->trend_filtered);
                uint32_t trend=DTS_STEADY;
                if(s->trend_filtered>=.020f||(s->trend_state==DTS_RISING&&s->trend_filtered>=.010f))trend=DTS_RISING;
                else if(s->trend_filtered<=-.020f||(s->trend_state==DTS_FALLING&&s->trend_filtered<=-.010f))trend=DTS_FALLING;
                if(trend!=s->trend_proposal){s->trend_proposal=trend;s->trend_dwell_us=0;}
                else if(s->previous_good)s->trend_dwell_us+=dt;
                if(s->trend_dwell_us>=80000U&&s->trend_state!=trend){s->trend_state=trend;++s->trend_changes;}
                s->valid=(uint32_t)(s->state!=DTS_UNKNOWN);
                s->trend_valid=s->valid&&s->trend_state!=DTS_TUNKNOWN;s->reason=s->valid?0:7;
            }
            s->previous_good=1;
        }
    }
    s->last_call=in.encoder_us;s->have_call=1;
}
void DobTrendShadow_Bind(void *buffer,size_t bytes){
    if(dob_trend_arena||dob_trend_shadow.abi)return;
    dob_trend_shadow.abi=1;
    if(!buffer||bytes<sizeof(DobTrendArena)||((uintptr_t)buffer&3U)){
        dob_trend_shadow.flags=DTS_BUFFER_ERROR;return;
    }
    dob_trend_arena=(DobTrendArena *)buffer;
    DobTrendClassifier_Reset(&dob_trend_arena->classifier);
    dob_trend_shadow.dt_min_us=UINT32_MAX;
}
void DobTrendShadow_Observe(DobTrendInput in,float ref,float accel,float rpm,float iq,uint32_t status){
    if(!dob_trend_arena||dob_trend_shadow.flags&DTS_DONE)return;
    DobTrendShadow *h=&dob_trend_shadow;DobTrendClassifier *s=&dob_trend_arena->classifier;
    if(!in.running){if(h->observations)h->flags|=DTS_DONE|DTS_STOPPED;return;}
    if(!h->observations)h->start_us=in.encoder_us;
    uint32_t dt=s->have_call?in.encoder_us-s->last_call:1000U,old_trend=s->trend_state;
    ++h->observations;if(dt<h->dt_min_us)h->dt_min_us=dt;if(dt>h->dt_max_us)h->dt_max_us=dt;
    DobTrendClassifier_Step(s,in);h->feature_updates+=s->updated;
    if(!(h->flags&DTS_ARMED)){
        if(in.encoder_us-h->start_us>=2000000U&&s->valid&&fabsf(ref)>=235&&fabsf(ref)<=245&&
           fabsf(accel)<.001f&&fabsf(rpm-ref)<=5){h->arm_qual_us+=dt;}
        else h->arm_qual_us=0;
        if(h->arm_qual_us>=40000U){h->flags|=DTS_ARMED;h->arm_us=in.encoder_us;h->baseline_a=h->peak_a=s->mean;}
    }
    if((h->flags&DTS_ARMED)&&s->valid){
        if(!(h->flags&DTS_TRIGGERED)&&s->mean-h->baseline_a>=.010f){
            h->flags|=DTS_TRIGGERED;h->proxy_rise_us=in.encoder_us;h->trigger_head=h->head;
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
    if(h->record_count&&in.encoder_us-h->last_record_us<DTS_RECORD_US)return;
    uint16_t flags=(uint16_t)(status&2047U);
    flags|=(uint16_t)(in.valid?2048U:0U)|(uint16_t)(in.filter_updated?4096U:0U)|
        (uint16_t)(s->valid?8192U:0U)|(uint16_t)(s->trend_valid?16384U:0U);
    if(h->flags&DTS_TRIGGERED)flags|=32768U;
    dob_trend_arena->points[h->head]=(DobTrendPoint){in.encoder_us,
        isfinite(in.disturbance_a)?in.disturbance_a:0,s->trend_filtered,rpm,iq,flags,(uint8_t)s->state,(uint8_t)s->trend_state};
    h->head=(h->head+1U)%DTS_POINTS;h->last_record_us=in.encoder_us;++h->record_count;
    if(h->flags&DTS_TRIGGERED){if(++h->post_count>=DTS_POST)h->flags|=DTS_DONE;}
    else if(h->pre_count<DTS_PRE)++h->pre_count;
}
