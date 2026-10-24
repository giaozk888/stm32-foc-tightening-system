#include <assert.h>
#include <math.h>
#include <string.h>
#include <stdio.h>
#include "ka_sync_diagnostic.h"
static void exercise(uint32_t base)
{
    KaSyncDiagnostic s={0};volatile KaSyncCurrent pub={0};KaSync_Reset(&s);
    uint32_t enc=base,seq=UINT32_MAX-(KA_SYNC_START_US/1000U+32U)*20U;uint16_t raw=16000;
    float speed=0;
    for (unsigned n=0;n<KA_SYNC_START_US/1000+64;++n) {
        enc=base+n*1000U;raw=(raw-4)&16383;seq+=20;
        KaSync_Publish(&pub,seq,enc+30,enc+60,.15f);
        KaSyncCurrent current;assert(KaSync_TryRead(&pub,&current));
        assert(current.source_seq==seq && current.source_us==enc+30 && current.iq==.15f);
        speed+=.001f/(.020f+.001f)*(14.6484375f-speed);
        KaSync_Observe(&s,enc+80,enc,1000,raw,-4,speed,.105f,0,&current,1);
    }
    assert(s.count==64 && s.flags==0 && sizeof s==1212);
    for (unsigned n=0;n<64;++n) {
        const KaSyncPoint *p=&s.points[n];
        assert(p->encoder_dt_us==1000 && p->task_age_us==80 && p->current_relative_us==30);
        assert(p->adc_seq_step==(n?20:0) && p->iq_0p1ma==1500 && p->friction_0p1ma==1050);
        assert(p->iq_minus_friction_lpf_0p1ma>=449 && p->iq_minus_friction_lpf_0p1ma<=451);
    }
    KaSyncDiagnostic before=s;
    KaSync_Observe(&s,0,0,0,0,0,0,0,0,0,0);assert(!memcmp(&s,&before,sizeof s));
    const unsigned char *p=(const unsigned char *)&s;
    for (unsigned n=0;n<sizeof s;++n) printf("%02x",p[n]);
    puts("");
    uint32_t generation=s.generation;KaSync_Reset(&s);
    assert(!s.count && !s.active && s.generation==generation+1 && s.net_iq_lpf==0);
}
int main(void)
{
    volatile KaSyncCurrent pub={0};KaSyncCurrent out={0};
    assert(!KaSync_TryRead(&pub,&out));pub.version=1;assert(!KaSync_TryRead(&pub,&out));
    KaSync_Publish(&pub,1,10,30,.2f); /* odd external version intentionally invalid */
    assert(!KaSync_TryRead(&pub,&out));
    pub.version=0;KaSync_Publish(&pub,2,20,40,-.2f);assert(KaSync_TryRead(&pub,&out));
    assert(out.iq==-.2f && out.source_seq==2);
    exercise(0);exercise(0U-KA_SYNC_START_US-30000U);
    KaSyncDiagnostic s={0};KaSync_Reset(&s);
    KaSyncCurrent c={2,1,KA_SYNC_START_US,KA_SYNC_START_US+40,4.5f};
    KaSync_Observe(&s,0,0,1000,0,0,0,0,0,&c,1);
    KaSync_Observe(&s,KA_SYNC_START_US+100,KA_SYNC_START_US,1000,0,0,0,.105f,1,&c,1);
    assert(s.points[0].flags & KAS_RANGE);assert(s.points[0].flags & KAS_SATURATED);
    return 0;
}
