#include "dob_trend_shadow.h"
#include "load_features.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static DobTrendInput input(uint32_t t,float load){
    return (DobTrendInput){.encoder_us=t,.observed_us=t+20,.source_us=t-20,
        .disturbance_a=load,.direction=1,.running=1,.valid=1,.filter_updated=1};
}
static void compare(void){
    DobTrendClassifier a;LoadFeatures b;LoadConfig config=Load_DefaultConfig();
    DobTrendClassifier_Reset(&a);Load_Reset(&b);
    for(unsigned n=0;n<7000;++n){
        float load=.001f+.0002f*sinf((float)n*.047f);
        if(n>=3000&&n<4600)load+=.035f;
        if(n>=5000&&n<5700)load+=(float)(n-5000)*.00004f;
        DobTrendInput in=input(100000+n*1000,load);
        if(n==1500||n==1501||n==1502||(n>=6100&&n<6130))in.valid=0;
        DobTrendClassifier_Step(&a,in);
        LoadInput x={.now_s=n*.001,.source_us=100020+n*1000-40,
            .disturbance_a=load,.direction=1,.enabled=1,.running=1,
            .valid=in.valid,.filter_updated=1};
        double y[LOAD_NY];Load_Step(&b,&config,x,y);
        assert(a.state==(unsigned)y[0]);assert(a.valid==(unsigned)y[1]);
        assert(a.trend_state==(unsigned)y[16]);assert(a.trend_valid==(unsigned)y[17]);
        assert(a.resets==(unsigned)y[9]);assert(a.updated==(unsigned)y[5]);
        assert(fabs(a.mean-y[2])<2e-7);assert(fabs(a.trend_filtered-y[18])<2e-6);
    }
}
static void quality_and_wrap(void){
    DobTrendClassifier a;DobTrendClassifier_Reset(&a);
    uint32_t origin=UINT32_MAX-50000U;
    for(unsigned n=0;n<400;++n)DobTrendClassifier_Step(&a,input(origin+n*1000,.002f));
    assert(a.valid&&a.trend_valid&&a.state==DTS_LIGHT&&a.trend_state==DTS_STEADY);
    float before=a.trend_filtered,mean=a.mean;uint32_t resets=a.resets;
    DobTrendInput bad=input(origin+400000,.7f);bad.filter_updated=0;
    DobTrendClassifier_Step(&a,bad);
    assert(!a.updated&&!a.valid&&a.mean==mean&&a.trend_filtered==before&&a.resets==resets);
    DobTrendClassifier_Step(&a,input(origin+401000,.002f));
    assert(a.valid&&a.resets==resets&&fabsf(a.mean-.002f)<1e-7f);
    for(unsigned n=402;n<425;++n){bad=input(origin+n*1000,.7f);bad.valid=0;DobTrendClassifier_Step(&a,bad);}
    assert(!a.valid&&a.resets==resets+1);
    bad=input(origin+425000,.7f);bad.source_us=bad.observed_us+1;
    DobTrendClassifier_Step(&a,bad);assert(!a.updated);
    bad=input(origin+426000,NAN);DobTrendClassifier_Step(&a,bad);assert(!a.updated);
}
static void recorder(void){
    static _Alignas(4) unsigned char memory[4608];
    memset(&dob_trend_shadow,0,sizeof dob_trend_shadow);dob_trend_arena=0;
    DobTrendShadow_Bind(memory,sizeof memory);assert(dob_trend_shadow.abi==1&&dob_trend_arena);
    for(unsigned n=0;n<4800;++n){
        DobTrendShadow_Observe(input(100000+n*1000,n<3000?.002f:.037f),240,0,240,.12f,0);
    }
    assert((dob_trend_shadow.flags&(DTS_ARMED|DTS_TRIGGERED|DTS_DONE))==(DTS_ARMED|DTS_TRIGGERED|DTS_DONE));
    assert(dob_trend_shadow.pre_count==32&&dob_trend_shadow.post_count==112);
    assert(dob_trend_shadow.trend_rise_us>dob_trend_shadow.proxy_rise_us);
    unsigned first=(dob_trend_shadow.trigger_head+DTS_POINTS-DTS_PRE)%DTS_POINTS;
    uint32_t prev=0;
    for(unsigned k=0;k<DTS_POINTS;++k){
        DobTrendPoint p=dob_trend_arena->points[(first+k)%DTS_POINTS];
        if(k)assert(p.encoder_us-prev==DTS_RECORD_US);
        prev=p.encoder_us;assert(isfinite(p.disturbance_a)&&isfinite(p.trend_a_s));
        assert((k<DTS_PRE)==!(p.flags&32768));
    }
    uint32_t saved=dob_trend_shadow.observations;
    DobTrendShadow_Observe(input(6000000,.1f),240,0,240,.2f,0);assert(saved==dob_trend_shadow.observations);
}
int main(void){
    assert(sizeof(DobTrendClassifier)==1012U);
    compare();quality_and_wrap();recorder();
    printf("PASS: float-vs-Simulink classifier 7000 epochs, quality gaps/spike, clock wrap, frozen ring; arena=%u header=%u\n",
        (unsigned)sizeof(DobTrendArena),(unsigned)sizeof(DobTrendShadow));return 0;
}
