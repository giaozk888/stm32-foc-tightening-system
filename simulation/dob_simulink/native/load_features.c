#include "load_features.h"
#include <math.h>
#include <string.h>
LoadConfig Load_DefaultConfig(void){
    /* Simulation starting values, NOT calibrated physical load thresholds. */
    return (LoadConfig){.010,.025,.005,.020,.030,.060,.60,.020,.100,.080,.5};
}
void Load_Reset(LoadFeatures *s){memset(s,0,sizeof *s);}
static void clear_quality(LoadFeatures *s){
    memset(s->good,0,sizeof s->good);s->count=s->head=0;
    s->state=s->proposal=LOAD_UNKNOWN;s->mean=s->trend=s->coverage=s->dwell=0;
    s->previous_good=s->have_source=0;++s->resets;
    s->trend_state=s->trend_proposal=TREND_UNKNOWN;s->trend_filtered=s->trend_dwell=0;
}
void Load_Step(LoadFeatures *s,const LoadConfig *c,LoadInput in,double y[LOAD_NY]){
    double dt=s->have_call?in.now_s-s->last_call:.001;
    unsigned reason=LR_OK,updated=0,valid=0,n=0;double age=0;
    int direction=in.direction>0?1:in.direction<0?-1:0;
    int active=in.enabled&&in.running&&!in.fault;
    if(!isfinite(c->light_a)||!isfinite(c->high_a)||!isfinite(c->hysteresis_a)||
       !isfinite(c->trend_a_s)||!isfinite(c->dwell_s)||!isfinite(c->min_span_s)||
       !isfinite(c->min_coverage)||!isfinite(c->long_gap_s)||
       !isfinite(c->trend_tau_s)||!isfinite(c->trend_dwell_s)||!isfinite(c->trend_exit_fraction)||
       c->light_a<0||c->high_a<=c->light_a||c->hysteresis_a<0||c->trend_a_s<=0||
       c->dwell_s<=0||c->min_span_s<=0||c->min_span_s>=.100||
       c->min_coverage<=0||c->min_coverage>1||c->long_gap_s<=.002||
       c->trend_tau_s<=0||c->trend_dwell_s<=0||c->trend_exit_fraction<=0||
       c->trend_exit_fraction>=1)reason=LR_CONFIG;
    else if(!in.enabled)reason=LR_DISABLED;
    else if(in.fault)reason=LR_FAULT;
    else if(!in.running)reason=LR_STOP;
    else if(!isfinite(in.now_s)||!isfinite(dt)||dt<.0005||dt>.002)reason=LR_TIME;
    else if(!direction||!isfinite(in.direction))reason=LR_DIRECTION;
    if(reason){
        if(s->count||s->state||s->have_source)clear_quality(s);
        s->direction=direction;
    }else{
        if(s->direction&&direction!=s->direction){clear_quality(s);reason=LR_DIRECTION;}
        s->direction=direction;
        /* Current observer time is the host control epoch +20 us. */
        age=(in.now_s*1e6+100020-in.source_us)*1e-6;
        int good=in.valid&&in.filter_updated&&isfinite(in.disturbance_a)&&
            isfinite(in.source_us)&&age>=-1e-7&&age<=.002&&
            (!s->have_source||in.source_us>s->last_source);
        if(s->have_source&&in.now_s-s->last_good>=c->long_gap_s-1e-9){
            clear_quality(s);reason=LR_LONG_GAP;
        }
        unsigned slot=s->head;s->head=(slot+1U)%LOAD_WINDOW;
        if(s->count<LOAD_WINDOW)++s->count;
        s->good[slot]=(unsigned char)good;
        s->time[slot]=in.now_s;
        if(good){
            s->value[slot]=direction*in.disturbance_a;
            s->last_source=in.source_us;s->last_good=in.now_s;s->have_source=1;++s->accepted;
        }else{
            ++s->rejected;s->previous_good=0;
            if(reason!=LR_LONG_GAP)reason=s->have_source?LR_SHORT_GAP:LR_SOURCE;
        }
        double sx=0,sy=0,sxx=0,sxy=0,first=in.now_s;
        for(unsigned k=0;k<LOAD_WINDOW;++k){
            if(!s->good[k])continue;
            double x=s->time[k]-in.now_s;
            ++n;sx+=x;sy+=s->value[k];sxx+=x*x;sxy+=x*s->value[k];
            if(s->time[k]<first)first=s->time[k];
        }
        s->coverage=(double)n/LOAD_WINDOW;
        if(good){
            /* Rejected observations never update mean/trend or dwell.
             * Window coverage may decay on wall time; it is NOT valid credit. */
            if(in.now_s-first<c->min_span_s-1e-9){reason=LR_WARMUP;s->dwell=0;}
            else if(s->coverage<c->min_coverage){reason=LR_COVERAGE;s->dwell=0;}
            else{
                double den=n*sxx-sx*sx;
                s->mean=sy/n;s->trend=den>1e-12?(n*sxy-sx*sy)/den:0;updated=1;
                unsigned label=LOAD_MEDIUM;
                if(s->mean>=c->high_a||
                    (s->state==LOAD_HIGH&&s->mean>=c->high_a-c->hysteresis_a))label=LOAD_HIGH;
                else if(s->mean<=c->light_a||
                    (s->state==LOAD_LIGHT&&s->mean<=c->light_a+c->hysteresis_a))label=LOAD_LIGHT;
                if(label!=s->proposal){s->proposal=label;s->dwell=0;}
                else if(s->previous_good)s->dwell+=dt;
                if(s->dwell>=c->dwell_s-1e-9){
                    if(s->state!=label){s->state=label;++s->transitions;}
                }
                /* Magnitude and trend are orthogonal. Missing epochs never
                 * supply extra EMA or confirmation time on recovery. */
                s->trend_filtered+=dt/(c->trend_tau_s+dt)*(s->trend-s->trend_filtered);
                unsigned trend=TREND_STEADY;
                double exit=c->trend_a_s*c->trend_exit_fraction;
                if(s->trend_filtered>=c->trend_a_s||
                    (s->trend_state==TREND_RISING&&s->trend_filtered>=exit))trend=TREND_RISING;
                else if(s->trend_filtered<=-c->trend_a_s||
                    (s->trend_state==TREND_FALLING&&s->trend_filtered<=-exit))trend=TREND_FALLING;
                if(trend!=s->trend_proposal){s->trend_proposal=trend;s->trend_dwell=0;}
                else if(s->previous_good)s->trend_dwell+=dt;
                if(s->trend_dwell>=c->trend_dwell_s-1e-9&&s->trend_state!=trend){
                    s->trend_state=trend;++s->trend_transitions;
                }
                valid=(unsigned)(s->state!=LOAD_UNKNOWN);
                reason=valid?LR_OK:LR_WARMUP;
            }
            s->previous_good=1;
        }
    }
    s->last_call=isfinite(in.now_s)?in.now_s:0;s->have_call=(unsigned)isfinite(in.now_s);
    double raw=isfinite(in.disturbance_a)?direction*in.disturbance_a:0;
    double result[LOAD_NY]={s->state,active?valid:0,s->mean,s->trend,s->coverage,updated,reason,
        s->accepted,s->rejected,s->resets,s->dwell*1000,n,raw,
        isfinite(age)?age*1000:0,s->transitions,s->proposal,
        s->trend_state,active&&valid&&s->trend_state!=TREND_UNKNOWN,s->trend_filtered,
        s->trend_transitions,s->trend_dwell*1000,s->trend_proposal};
    memcpy(y,result,sizeof result);
}
