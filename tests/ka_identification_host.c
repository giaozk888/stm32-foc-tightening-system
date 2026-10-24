#include <assert.h>
#include <math.h>
#include <string.h>
#include "ka_identification.h"
static void exercise(uint32_t start)
{
    KaIdentification s={0};KaIdent_Reset(&s);
    for (unsigned n=0;n<=2400;++n) {
        float speed=(float)n*.2f;
        SpeedAccelFfFrame f={.seq=n+1U,.valid=1,.speed_meas_rpm=speed,
            .speed_ref_rpm=speed+5,.iq_meas_a=.15f,.iq_ref_a=.49f};
        SpeedAccelFfFrame before=f;
        uint32_t now=start+n*1000U;
        KaIdent_Observe(&s,&f,.105f,now,now-100U,n*20U);
        assert(!memcmp(&f,&before,sizeof f));
    }
    assert(s.count==24 && sizeof s==1032);
    for (unsigned i=0;i<s.count;++i) {
        const KaIdentFrame *f=&s.frames[i];
        assert(f->flags==0 && (uint32_t)(f->end_us-f->start_us)==100000);
        assert(fabsf((f->speed_end_rpm-f->speed_start_rpm)/.1f-200)<.001f);
        assert(fabsf(f->mean_iq_a-.15f)<.000001f);
        assert(fabsf(f->mean_friction_a-.105f)<.000001f);
    }
    KaIdentification before=s;
    SpeedAccelFfFrame f={.valid=1};KaIdent_Observe(&s,&f,0,0,0,0);
    assert(!memcmp(&s,&before,sizeof s));
    KaIdent_Reset(&s);assert(s.count==0 && s.samples==0 && s.generation==2);
}
int main(void)
{
    exercise(100U);exercise(0xffff0000U);
    KaIdentification s={0};KaIdent_Reset(&s);
    for (unsigned n=0;n<=101;++n) {
        SpeedAccelFfFrame f={.seq=n+1,.valid=1,.iq_meas_a=.2f,.speed_meas_rpm=20};
        if (n==30) f.saturated=1;
        KaIdent_Observe(&s,&f,.1f,n*1000,n*1000,0); /* ADC never advances. */
    }
    assert(s.frames[0].flags & KAI_SATURATED);
    assert(s.frames[0].flags & KAI_CURRENT_STALE);
    KaIdent_Reset(&s);
    for (unsigned n=0;n<=101;++n) {
        SpeedAccelFfFrame f={.seq=n+1,.valid=1,.iq_meas_a=.2f,.speed_meas_rpm=20};
        if (n==30) f.iq_meas_a=NAN;
        KaIdent_Observe(&s,&f,.1f,n*1000,n*1000,n+1);
    }
    assert(s.frames[0].flags & KAI_BAD_INPUT);
    KaIdent_Reset(&s);
    for (unsigned n=0;n<=101;++n) {
        SpeedAccelFfFrame f={.seq=n+1,.valid=1,.iq_meas_a=.2f,.speed_meas_rpm=20};
        uint32_t now=n*1000U+(n>=30?6000U:0U);
        KaIdent_Observe(&s,&f,.1f,now,now-3000U,n+1);
    }
    assert(s.frames[0].flags & KAI_SAMPLE_GAP);
    assert(s.frames[0].flags & KAI_ENCODER_STALE);
    return 0;
}
