#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "foc_dq_audit.h"

int main(void)
{
    FocDqAudit a={0};
    FocDqAuditFrame f={.seq=1,.us=100,.flags=DQA_ON,.mech_rpm=0,.we_rad_s=0,.id=.1f,.iq=.2f};
    assert(FocDqDecoupling_Apply(1,f.we_rad_s,f.id,f.iq,&f.vd_dec,&f.vq_dec));
    FocDqAudit_Record(&a,&f);
    assert(a.stats.zero_n==1 && a.stats.zero_d_max==0 && a.stats.zero_q_max==0);
    assert(a.stats.first_sat_us==UINT32_MAX);
    f.seq++;f.us=UINT32_MAX-20000;f.flags=DQA_ON|DQA_RUNNING;
    f.we_rad_s=10;f.mech_rpm=10.0f/(10*6.283185307179586f/60);
    FocDqDecoupling_Apply(1,f.we_rad_s,f.id,f.iq,&f.vd_dec,&f.vq_dec);
    FocDqAudit_Record(&a,&f);
    assert(a.stats.start_n==1 && a.latest.elapsed_us==0);
    uint32_t start=f.us;
    f.seq++;f.us=start+250000U;FocDqAudit_Record(&a,&f);
    assert(a.stats.start_n==2 && a.latest.elapsed_us==250000);
    assert(fabsf(a.stats.start_d_max-fabsf(f.vd_dec))<1e-10f);
    f.seq++;f.us=start+500000U;f.flags|=DQA_CRUISE;FocDqAudit_Record(&a,&f);
    assert(a.stats.start_n==2 && a.stats.cruise_n==1);
    assert(a.stats.cruise_d_sum==f.vd_dec && a.stats.cruise_q_sum==f.vq_dec);
    f.seq++;f.us=start+600000U;f.flags|=DQA_SATURATED;FocDqAudit_Record(&a,&f);
    assert(a.stats.first_sat_us==600000 && a.stats.sat_n==1);
    assert(a.stats.we_chain_error_max<1e-5f && a.stats.config_bad==0);
    assert((a.stats.nominal_d_bad>0)==((DECOUPLING_SIGN_MODE&1)!=0));
    assert((a.stats.nominal_q_bad>0)==((DECOUPLING_SIGN_MODE&2)!=0));
    FocDqAuditFrame saved=a.latest;
    f.flags=0;f.seq++;FocDqAudit_Record(&a,&f);
    assert(!memcmp(&saved,&a.latest,sizeof saved));
    f.flags=DQA_ON|DQA_RUNNING;f.we_rad_s=NAN;FocDqAudit_Record(&a,&f);
    assert(a.stats.invalid_n==1 && !memcmp(&saved,&a.latest,sizeof saved));
    f.we_rad_s=1000;f.mech_rpm=0;f.vd_dec=0;f.vq_dec=1;
    FocDqAudit_Record(&a,&f);
    assert(a.stats.config_bad==1 && a.stats.we_chain_error_max>=1000);
    puts("PASS actual dq audit: zero, startup, wrap, cruise, saturation, signs, retained stop");
    return 0;
}
