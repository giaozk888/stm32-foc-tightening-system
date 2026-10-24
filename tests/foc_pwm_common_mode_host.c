#include "foc_pwm_common_mode.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static unsigned accepted,rejected;
static const FocWindowConfig cfg={4249,85,85,14,50,FOC_SENSE_LOW_SIDE_UV,
                                 1700,FOC_SAMPLE_LATE_BEFORE_PEAK};
static uint16_t bounded(float x)
{
    if (x<.05f) x=.05f;
    if (x>.95f) x=.95f;
    return (uint16_t)(x*4250.0f);
}
/* Independent edge-distance oracle; no reuse of allocator cap formula. */
static int safe(const uint16_t phase[3],int t,unsigned reserve)
{
    int end=t+64,period=8498,guard=170+(int)reserve;
    if (t<=0 || end>=4249) return 0;
    for (unsigned i=0;i<3;++i) {
        if (phase[i]<212 || phase[i]>4037) return 0;
        if (i<2 && t<(int)phase[i]+85+1700+(int)reserve) return 0;
        for (int k=-1;k<=1;++k) {
            int edge=k*period+phase[i],reverse=k*period+period-phase[i];
            if (!(end<=edge-guard || t>=edge+guard) ||
                !(end<=reverse-guard || t>=reverse+guard)) return 0;
        }
    }
    return 1;
}
static void check(float u,float v,float w,int exhaustive)
{
    const uint16_t original[3]={bounded(u),bounded(v),bounded(w)};
    FocWindowPlan p; memset(&p,0xa5,sizeof p); int16_t offset=123;
    FocWindowStatus result=FocPwmCommonMode_Plan(&cfg,u,v,w,4184,85,&p,&offset);
    if (result==FOC_WINDOW_OK) {
        ++accepted;
        assert(offset<=0 && p.trigger==4184 && p.slack_ticks>=85);
        for (unsigned i=0;i<3;++i) assert((int)p.phase[i]-(int)original[i]==offset);
        assert((int)p.phase[0]-p.phase[1]==(int)original[0]-original[1]);
        assert((int)p.phase[1]-p.phase[2]==(int)original[1]-original[2]);
        assert(safe(p.phase,p.trigger,85));
        if (offset<0) {
            uint16_t closer[3]={p.phase[0]+1U,p.phase[1]+1U,p.phase[2]+1U};
            assert(!safe(closer,4184,85)); /* Minimal shift, not full-rail clamping. */
        }
    } else {
        ++rejected; assert(result==FOC_WINDOW_TOO_SHORT && !offset);
        const FocWindowPlan zero={0}; assert(!memcmp(&p,&zero,sizeof p));
    }
    if (exhaustive) {
        int found=0;
        for (int delta=0;delta>=-(int)original[0] &&
                delta>=-(int)original[1] && delta>=-(int)original[2];--delta) {
            uint16_t candidate[3]={(uint16_t)(original[0]+delta),
                (uint16_t)(original[1]+delta),(uint16_t)(original[2]+delta)};
            if (safe(candidate,4184,85)) {
                assert(result==FOC_WINDOW_OK && delta==offset); found=1; break;
            }
        }
        assert(found==(result==FOC_WINDOW_OK));
    }
}
int main(void)
{
    FocWindowPlan p; int16_t offset;
    assert(FocPwmCommonMode_Plan(&cfg,.4450235664844513f,.5650515556335449f,
        .43494847416877747f,4184,85,&p,&offset)==FOC_WINDOW_OK);
    assert(offset==-87 && p.phase[0]==1804 && p.phase[1]==2314 && p.phase[2]==1761);
    assert(p.slack_ticks==85 && p.trigger==4184);
    assert(FocPwmCommonMode_Plan(&cfg,.5f,.5f,.5f,4184,85,&p,&offset)==FOC_WINDOW_OK);
    assert(!offset && p.phase[0]==2125 && p.phase[1]==2125 && p.phase[2]==2125);
    assert(FocPwmCommonMode_Plan(&cfg,.95f,.05f,.5f,4184,85,&p,&offset)==FOC_WINDOW_TOO_SHORT);
    assert(!offset && !p.phase[0] && !p.trigger);
    assert(FocPwmCommonMode_Plan(&cfg,NAN,.5f,.5f,4184,85,&p,&offset)==FOC_WINDOW_BAD_ARGUMENT);
    assert(FocPwmCommonMode_Plan(&cfg,.5f,INFINITY,.5f,4184,85,&p,&offset)==FOC_WINDOW_BAD_ARGUMENT);
    assert(FocPwmCommonMode_Plan(NULL,.5f,.5f,.5f,4184,85,&p,&offset)==FOC_WINDOW_BAD_ARGUMENT);
    assert(FocPwmCommonMode_Plan(&cfg,.5f,.5f,.5f,4184,85,NULL,&offset)==FOC_WINDOW_BAD_ARGUMENT);
    assert(FocPwmCommonMode_Plan(&cfg,.5f,.5f,.5f,4184,85,&p,NULL)==FOC_WINDOW_BAD_ARGUMENT);
    assert(FocPwmCommonMode_Plan(&cfg,.5f,.5f,.5f,0,85,&p,&offset)==FOC_WINDOW_BAD_ARGUMENT);
    assert(FocPwmCommonMode_Plan(&cfg,.5f,.5f,.5f,4200,85,&p,&offset)==FOC_WINDOW_TOO_SHORT);
    FocWindowConfig wrong=cfg; wrong.topology=FOC_SENSE_INLINE;
    assert(FocPwmCommonMode_Plan(&wrong,.5f,.5f,.5f,4184,85,&p,&offset)==FOC_WINDOW_BAD_ARGUMENT);
    wrong=cfg; wrong.placement=FOC_SAMPLE_WINDOW_MIDPOINT;
    assert(FocPwmCommonMode_Plan(&wrong,.5f,.5f,.5f,4184,85,&p,&offset)==FOC_WINDOW_BAD_ARGUMENT);
    for (unsigned u=5;u<=95;++u) for(unsigned v=5;v<=95;++v) for(unsigned w=5;w<=95;++w)
        check(u/100.0f,v/100.0f,w/100.0f,u%10==5 && v%10==5 && w%10==5);
    check(-1,2,.5f,1); check(.5f,-3,5,1);
    assert(accepted && rejected);
    printf("PASS common-mode %u accepted / %u rejected, exact differences, minimal offset, independent edge oracle\n",accepted,rejected);
    return 0;
}
