#include "ka_full_diagnostic.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static void exercise(uint32_t start,int bad)
{
    KaFullDiagnostic s={0};s.publish_cycles_max=81;KaFull_Reset(&s);
    KaSyncCurrent c={2,0xfffff000U,start+30,start+60,.13f};
    float filtered=0,travel=0;int32_t last_count=0;
    for (unsigned i=0;i<=2400;++i) {
        float t=(float)i*.001f,accel,v;
        if(t<.2f) {accel=1000*t;v=500*t*t;}
        else if(t<1.2f) {accel=200;v=20+200*(t-.2f);}
        else if(t<1.4f) {float x=t-1.2f;accel=200-1000*x;v=220+200*x-500*x*x;}
        else {accel=0;v=240;}
        filtered+=.001f/(.020f+.001f)*(v-filtered);
        travel+=v*16384/60*.001f;int32_t count=(int32_t)travel,delta=-(count-last_count);last_count=count;
        uint32_t enc=start+i*1000U;c.source_seq+=20;c.source_us=enc+30;c.published_us=enc+60;
        c.iq=.105f+.025f+.0001f*accel;
        if(bad && i==301)c.source_us=enc-400;
        KaFull_Observe(&s,enc+80,enc,1000,(uint16_t)((-count)&16383),delta,filtered,v,accel,.105f,
                       (uint8_t)(bad && i==401),&c,(uint8_t)(!(bad && i==501)));
    }
    assert(s.count==240 && s.observations==2401 && s.publish_cycles_max==81);
    assert(s.last_encoder_us-s.first_encoder_us==2400000U);
    assert((s.flags!=0)==(bad!=0));
    for(unsigned i=0;i<240;++i)assert(s.points[i].samples==10 && s.points[i].interval_us==10000);
    KaFullDiagnostic before=s;KaFull_Observe(&s,0,0,0,0,0,0,0,0,0,0,0,0);
    assert(!memcmp(&s,&before,sizeof s));
    const unsigned char *p=(const unsigned char *)&s;
    for(unsigned i=0;i<sizeof s;++i)printf("%02x",p[i]);
    puts("");
    unsigned generation=s.generation;KaFull_Reset(&s);
    assert(s.generation==generation+1 && !s.count && !s.active && !s.flags && s.publish_cycles_max==81);
}
int main(void) {exercise(0,0);exercise(0U-50000U,0);exercise(0,1);return 0;}
