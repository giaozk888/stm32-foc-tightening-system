#include "dob_trend_continuous.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static _Alignas(4) unsigned char memory[4608];
static DobTrendInput input(uint32_t t,float load){
    return (DobTrendInput){.encoder_us=t,.observed_us=t+20,.source_us=t-20,.disturbance_a=load,
        .direction=1,.running=1,.valid=1,.filter_updated=1};
}
static void reset(void){
    memset(memory,0,sizeof memory);memset(&dob_trend_continuous,0,sizeof dob_trend_continuous);
    dob_trend_continuous_arena=0;DobTrendContinuous_Bind(memory,sizeof memory);
    assert(dob_trend_continuous.abi==2&&dob_trend_continuous_arena);
}
static void complete_eight_seconds(void){
    reset();DobTrendClassifier reference;DobTrendClassifier_Reset(&reference);
    for(unsigned n=0;n<8000;++n){
        float load=.002f;
        if(n>=2600&&n<3100)load=.035f; /* early small event */
        if(n>=5000&&n<6000)load=.12f; /* later real brake and unloading */
        DobTrendInput in=input(100000+n*1000,load);
        if(n==4200||n==4201)in.filter_updated=0;
        DobTrendClassifier_Step(&reference,in);
        DobTrendContinuous_Observe(in,240,0,240.04f,.1234f,0);
        DobTrendClassifier *actual=&dob_trend_continuous_arena->classifier;
        assert(memcmp(actual,&reference,sizeof reference)==0);
    }
    DobTrendContinuous *h=&dob_trend_continuous;
    assert(h->observations==8000&&h->record_count==134&&h->record_overflow==0);
    assert(!(h->flags&DTS_DONE)&&h->last_record_us==8080000);
    assert(dob_trend_continuous_arena->points[0].encoder_us==100000);
    assert(dob_trend_continuous_arena->points[133].encoder_us==8080000);
    assert(dob_trend_continuous_arena->points[100].mean_a>.1f);
    assert(dob_trend_continuous_arena->points[100].rpm_deci==2400);
    assert(dob_trend_continuous_arena->points[100].iq_ma==123);
    unsigned after=0,fall=0;
    for(unsigned k=0;k<h->event_count&&k<DTC_EVENTS;++k){
        DobTrendEvent e=dob_trend_continuous_arena->events[k];
        if(e.encoder_us>5100000)++after;
        if(e.encoder_us>6100000&&(e.type&255U)==DTC_TREND&&e.trend==DTS_FALLING)++fall;
    }
    assert(after&&fall);
}
static void rings_never_stop_classification(void){
    reset();uint32_t origin=UINT32_MAX-4000000U;
    for(unsigned n=0;n<14000;++n){
        float load=(n/200U)%2U?.1f:.002f;
        DobTrendContinuous_Observe(input(origin+n*1000,load),240,0,-239.96f,-.1234f,0);
    }
    DobTrendContinuous *h=&dob_trend_continuous;
    assert(h->observations==14000&&h->record_count==234&&h->record_overflow==96);
    assert(h->event_count>DTC_EVENTS&&h->event_dropped==h->event_count-DTC_EVENTS);
    assert((h->flags&(DTC_RECORD_WRAP|DTC_EVENT_WRAP))==(DTC_RECORD_WRAP|DTC_EVENT_WRAP));
    assert(!(h->flags&DTS_DONE));
    DobTrendContinuousPoint last=dob_trend_continuous_arena->points[(h->head+DTC_POINTS-1U)%DTC_POINTS];
    assert(last.encoder_us==origin+13980000U&&last.rpm_deci==-2400&&last.iq_ma==-123);
    uint32_t prev=0;unsigned first=(h->event_head+DTC_EVENTS-DTC_EVENTS)%DTC_EVENTS;
    for(unsigned k=0;k<DTC_EVENTS;++k){
        uint32_t now=dob_trend_continuous_arena->events[(first+k)%DTC_EVENTS].encoder_us;
        if(k)assert(now-prev<1000000U);
        prev=now;
    }
    DobTrendInput stop=input(origin+14000000U,.002f);stop.running=0;
    DobTrendContinuous_Observe(stop,0,0,0,0,0);
    assert((h->flags&(DTS_DONE|DTS_STOPPED))==(DTS_DONE|DTS_STOPPED));
    DobTrendContinuous_Observe(input(origin+14001000U,.2f),240,0,240,.2f,0);
    assert(h->observations==14000);
}
int main(int argc,char **argv){
    complete_eight_seconds();
    if(argc==2){FILE *f=fopen(argv[1],"wb");assert(f);assert(fwrite(&dob_trend_continuous,1,100,f)==100);
        assert(fwrite(memory,1,4608,f)==4608);assert(fclose(f)==0);}
    rings_never_stop_classification();
    puts("PASS:8000 epochs identical, early trigger then late load/unload, full8s frames, record/event wrap, clock wrap, STOP");
    return 0;
}
