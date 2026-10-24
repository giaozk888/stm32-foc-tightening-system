#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "speed_accel_feedforward.h"
static int near(float a,float b) { return fabsf(a-b)<1e-5f; }
static SpeedAccelFfResult run(float prev,float candidate,float p,float accel,unsigned release,unsigned enabled)
{ return SpeedAccelFf_Apply(prev,candidate,p,accel,SPEED_ACCEL_FF_KA_A_PER_RPM_S,.5f,.35f,(uint8_t)release,(uint8_t)enabled); }
int main(void)
{
    for(int sign=-1;sign<=1;sign+=2) {
        float s=(float)sign;
        SpeedAccelFfResult r=run(s*.1f,s*.11f,s*.2f,s*200,0,1);
        assert(near(r.iq_ff_a,s*.0375f) && near(r.iq_ref_a,s*.3475f));
        assert(!r.saturated && !r.aw_limited);
        /* I growth is admitted only to the combined PI+FF boundary. */
        r=run(s*.24f,s*.29f,s*.2f,s*200,0,1);
        assert(near(r.integral_a,s*.2625f) && near(r.iq_ref_a,s*.5f));
        assert(r.saturated && r.aw_limited);
        r=run(s*.29f,s*.31f,s*.2f,s*200,0,1);
        assert(near(r.integral_a,s*.29f) && near(r.iq_ref_a,s*.5f));
        /* Opposite FF creates real headroom: do not test PI alone. */
        r=run(s*.2f,s*.21f,s*.3f,-s*200,0,1);
        assert(near(r.integral_a,s*.21f) && near(r.iq_ref_a,s*.4725f));
        assert(!r.saturated && !r.aw_limited);
        r=run(s*.3f,s*.29f,s*.9f,s*200,1,1);
        assert(near(r.integral_a,s*.29f) && near(r.iq_ref_a,s*.5f));
        for(unsigned i=0;i<10000;++i) {
            r=run(0,s*.0002f,s*.6f,s*200,0,1);
            assert(r.integral_a==0 && fabsf(r.iq_ref_a)==.5f);
        }
    }
    for(int p=-100;p<=100;p+=5) for(int i=-35;i<=35;i+=5)
      for(int di=-5;di<=5;++di) for(int a=-200;a<=200;a+=100) {
        float previous=i*.01f,candidate=(i+di)*.01f;
        SpeedAccelFfResult r=run(previous,candidate,p*.01f,(float)a,0,1);
        assert(fabsf(r.iq_ref_a)<=.5f && fabsf(r.integral_a)<=.35f);
        assert(r.iq_raw_a==r.iq_pi_a+r.iq_ff_a);
        assert(near(r.iq_ref_a,fmaxf(-.5f,fminf(.5f,r.iq_raw_a))));
        SpeedPiAntiWindupResult old=SpeedPiAntiWindup_Apply(previous,candidate,p*.01f,.5f,.35f,0);
        SpeedAccelFfResult off=run(previous,candidate,p*.01f,(float)a,0,0);
        assert(off.integral_a==old.integral_A && off.iq_ref_a==old.current_A && off.iq_ff_a==0);
    }
    SpeedAccelFfStats stats; SpeedAccelFf_StatsReset(&stats);
    SpeedAccelFfFrame f={.valid=1,.command_rpm=240,.speed_ref_rpm=100,.speed_meas_rpm=90,
        .accel_ref_rpm_s=200,.iq_ref_a=.5f,.iq_meas_a=.48f,.speed_integrator_a=.3f,.saturated=1};
    for(unsigned i=0;i<100;++i) SpeedAccelFf_Observe(&stats,&f,.001f);
    assert(near(stats.accel_time_s,.1f) && near(stats.accel_error_integral/stats.accel_time_s,10));
    assert(stats.decel_time_s==0 && stats.overshoot_rpm==0);
    assert(near(stats.saturation_s,.1f) && near(stats.saturation_run_max_s,.1f));
    f.speed_ref_rpm=240; f.speed_meas_rpm=250; f.accel_ref_rpm_s=0; f.saturated=0;
    for(unsigned i=0;i<300;++i) SpeedAccelFf_Observe(&stats,&f,.001f);
    assert(stats.settled && near(stats.overshoot_rpm,10));
    assert(near(stats.iq_peak_a,.5f) && near(stats.iq_measured_peak_a,.48f));
    assert(near(stats.integrator_peak_a,.3f));
    f.speed_meas_rpm=270; SpeedAccelFf_Observe(&stats,&f,.001f);
    assert(!stats.settled && stats.settling_time_s==-1);
    f.command_rpm=0; f.speed_ref_rpm=100; f.speed_meas_rpm=95; f.accel_ref_rpm_s=-100;
    for(unsigned i=0;i<100;++i) SpeedAccelFf_Observe(&stats,&f,.001f);
    assert(near(stats.decel_time_s,.1f) && near(stats.decel_error_integral/stats.decel_time_s,5));
    assert(stats.segment==2);
    f.speed_ref_rpm=0; f.speed_meas_rpm=0; f.accel_ref_rpm_s=0;
    for(unsigned i=0;i<300;++i) SpeedAccelFf_Observe(&stats,&f,.001f);
    assert(stats.settled);
    unsigned count=stats.samples;
    SpeedAccelFf_Observe(&stats,&f,NAN); assert(stats.samples==count);
    f.valid=0; SpeedAccelFf_Observe(&stats,&f,.001f); assert(stats.samples==count);
    SpeedAccelFf_StatsReset(&stats);
    assert(stats.samples==0 && stats.settling_time_s==-1);
    puts("PASS signed FF, combined anti-windup, OFF equivalence, limits and phase/settling metrics");
    return 0;
}
