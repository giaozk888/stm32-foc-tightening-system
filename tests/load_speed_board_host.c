#include "dob_load_speed_candidate.h"
#include "dob_trend_continuous.h"
#include <string.h>
static DobTrendContinuousArena arena;
__declspec(dllexport) void board_reset(void){
    memset(&dob_load_speed,0,sizeof dob_load_speed);memset(&arena,0,sizeof arena);
    memset(&dob_trend_continuous,0,sizeof dob_trend_continuous);dob_trend_continuous_arena=0;
    DobTrendContinuous_Bind(&arena,sizeof arena);
}
__declspec(dllexport) void board_step(const double *u,double *out){
    DobTrendClassifier *c=&arena.classifier;
    c->valid=(uint32_t)u[3];c->state=(uint32_t)u[4];c->trend_valid=(uint32_t)u[5];
    c->trend_state=(uint32_t)u[6];c->mean=(float)u[9];c->last_call=(uint32_t)u[0]-(uint32_t)u[10];
    float target=DobLoadSpeed_Select((uint32_t)u[0],(uint32_t)u[1],(float)u[7],(float)u[8],(float)u[11],(float)u[12]);
    double y[]={target,dob_load_speed.policy.slow,dob_load_speed.policy.reason,
        dob_load_speed.policy.transitions,dob_load_speed.policy.high_us,dob_load_speed.policy.release_us,
        dob_load_speed.samples,dob_load_speed.slow_epochs,dob_load_speed.invalid_epochs};
    memcpy(out,y,sizeof y);
}
__declspec(dllexport) void board_tail(void *out){
    memcpy(out,&arena.classifier.value[75],100);memcpy((unsigned char *)out+100,&arena.classifier.stamp[75],100);
}
__declspec(dllexport) void board_quality_clear(void){
    DobTrendClassifier *c=&arena.classifier;c->have_source=1;c->last_good=1;
    c->have_call=1;c->last_call=999000;
    DobTrendClassifier_Step(c,(DobTrendInput){.encoder_us=1000000,.observed_us=1000020,.direction=1,.running=1});
}
