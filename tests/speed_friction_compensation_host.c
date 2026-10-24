#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "speed_friction_compensation.h"
static int near(float a,float b){return fabsf(a-b)<1e-5f;}
static SpeedFrictionResult run(float prev,float candidate,float p,float accel,float speed,unsigned release,unsigned acc,unsigned on)
{
    return SpeedFriction_Apply(prev,candidate,p,accel,.0001875f,speed,.2f,2,.5f,.35f,
        (uint8_t)release,(uint8_t)acc,(uint8_t)on);
}
int main(void)
{
    for(int sign=-1;sign<=1;sign+=2) {
        float s=(float)sign;
        SpeedFrictionResult r=run(s*.01f,s*.02f,s*.1f,s*200,s*240,0,1,1);
        assert(near(r.iq_fric_a,s*.2f) && near(r.speed.iq_ff_a,s*.0375f));
        assert(near(r.speed.iq_ref_a,s*.3575f));
        r=run(s*.04f,s*.15f,s*.2f,s*200,s*240,0,1,1);
        assert(near(r.speed.integral_a,s*.0625f));
        assert(near(r.speed.iq_ref_a,s*.5f) && r.speed.aw_limited && r.speed.saturated);
        r=run(s*.25f,s*.26f,s*.3f,s*200,-s*240,0,1,1);
        assert(near(r.speed.iq_ref_a,s*.3975f) && !r.speed.aw_limited);
        r=run(s*.3f,s*.29f,s*.9f,s*200,s*240,1,1,1);
        assert(near(r.speed.integral_a,s*.29f) && fabsf(r.speed.iq_ref_a)==.5f);
        for(unsigned i=0;i<10000;++i) {
            r=run(0,s*.001f,s*.4f,s*200,s*240,0,1,1);
            assert(r.speed.integral_a==0 && fabsf(r.speed.iq_ref_a)==.5f);
        }
        r=run(0,.01f,.1f,0,s*nextafterf(2.0f,3.0f),0,1,1);
        assert(near(r.iq_fric_a,s*.2f));
    }
    for(int p=-100;p<=100;p+=10) for(int i=-35;i<=35;i+=5)
      for(int di=-5;di<=5;++di) for(int a=-200;a<=200;a+=100)
      for(int speed=-3;speed<=3;++speed) for(unsigned acc=0;acc<=1;++acc) {
        float prev=i*.01f,candidate=(i+di)*.01f;
        SpeedFrictionResult r=run(prev,candidate,p*.01f,(float)a,(float)speed,0,acc,1);
        assert(fabsf(r.speed.iq_ref_a)<=.5f && fabsf(r.speed.integral_a)<=.35f);
        assert(r.speed.iq_raw_a==(r.speed.iq_pi_a+r.speed.iq_ff_a)+r.iq_fric_a);
        assert(near(r.iq_fric_a,speed>2?.2f:speed< -2?-.2f:0));
        SpeedAccelFfResult old=SpeedAccelFf_Apply(prev,candidate,p*.01f,(float)a,.0001875f,.5f,.35f,0,(uint8_t)acc);
        SpeedFrictionResult off=run(prev,candidate,p*.01f,(float)a,(float)speed,0,acc,0);
        assert(off.speed.integral_a==old.integral_a && off.speed.iq_ref_a==old.iq_ref_a);
        assert(off.speed.iq_raw_a==old.iq_raw_a && off.speed.iq_ff_a==old.iq_ff_a);
        if(abs(speed)<=2) assert(r.speed.integral_a==old.integral_a && r.speed.iq_ref_a==old.iq_ref_a);
    }
    SpeedFrictionStats stats; SpeedFriction_StatsReset(&stats);
    SpeedFrictionFrame f={.control={.valid=1,.command_rpm=20,.speed_ref_rpm=10,.speed_meas_rpm=0,
        .accel_ref_rpm_s=100,.iq_pi_a=.15f,.iq_ref_a=.35f,.iq_meas_a=.3f,.speed_integrator_a=.1f}};
    for(unsigned i=0;i<100;++i) SpeedFriction_Observe(&stats,&f,.001f);
    assert(stats.positive.start_delay_s<0);
    f.control.speed_meas_rpm=5;
    for(unsigned i=0;i<60;++i) SpeedFriction_Observe(&stats,&f,.001f);
    assert(near(stats.positive.start_delay_s,.1f));
    assert(fabsf(stats.positive.low_error_integral/stats.positive.low_time_s-8.125f)<1e-4f);
    f.control.speed_ref_rpm=20;f.control.speed_meas_rpm=18;f.control.accel_ref_rpm_s=0;
    for(unsigned i=0;i<100;++i) SpeedFriction_Observe(&stats,&f,.001f);
    assert(near(stats.positive.cruise_error_integral/stats.positive.cruise_time_s,2));
    assert(near(stats.positive.pi_peak_a,.15f) && near(stats.positive.iq_peak_a,.35f));
    f.control.command_rpm=-20;f.control.speed_ref_rpm=-20;f.control.speed_meas_rpm=5;
    for(unsigned i=0;i<100;++i) SpeedFriction_Observe(&stats,&f,.001f);
    assert(near(stats.negative.wrong_direction_time_s,.1f) && stats.negative.start_delay_s<0);
    f.control.speed_meas_rpm=-18;
    for(unsigned i=0;i<60;++i) SpeedFriction_Observe(&stats,&f,.001f);
    assert(near(stats.negative.start_delay_s,.1f) && stats.positive.start_delay_s>=0);
    unsigned count=stats.negative.samples;
    f.control.valid=0;SpeedFriction_Observe(&stats,&f,.001f);assert(stats.negative.samples==count);
    f.control.valid=1;SpeedFriction_Observe(&stats,&f,NAN);assert(stats.negative.samples==count);
    SpeedFriction_StatsReset(&stats);assert(stats.positive.samples==0 && stats.negative.start_delay_s<0);
    f.control.valid=1;f.control.command_rpm=20;f.control.speed_ref_rpm=10;
    f.control.speed_meas_rpm=5;SpeedFriction_Observe(&stats,&f,.001f);
    f.control.speed_meas_rpm=0;SpeedFriction_Observe(&stats,&f,.001f);
    assert(stats.positive.start_delay_s<0);
    f.control.speed_meas_rpm=5;
    for(unsigned i=0;i<60;++i) SpeedFriction_Observe(&stats,&f,.001f);
    assert(stats.positive.start_delay_s>=0);
    f.control.command_rpm=0;SpeedFriction_Observe(&stats,&f,.001f);
    f.control.command_rpm=20;f.control.speed_meas_rpm=0;
    SpeedFriction_Observe(&stats,&f,.001f);assert(stats.positive.start_delay_s<0);
    puts("PASS Coulomb/deadband/OFF/combined AW and directional evidence");
}
