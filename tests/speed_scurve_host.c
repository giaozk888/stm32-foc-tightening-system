#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "speed_scurve.h"
#include "tightening_rundown_guard.h"

static float tick(SpeedScurve *s, float target, float dt)
{
    float v = s->speed_rpm, a = s->acceleration_rpm_s;
    float next = SpeedScurve_Step(s, target, dt);
    assert(isfinite(next) && isfinite(s->acceleration_rpm_s));
    assert(fabsf(s->acceleration_rpm_s) <= SPEED_SCURVE_MAX_ACCEL_RPM_S + .002f);
    assert(fabsf(s->acceleration_rpm_s - a) <= SPEED_SCURVE_MAX_JERK_RPM_S2 * dt + .003f);
    assert(fabsf(next - v) <= SPEED_SCURVE_MAX_ACCEL_RPM_S * dt + .002f);
    return next;
}

static void move(float start, float target, float dt, float expected_s)
{
    SpeedScurve s;
    SpeedScurve_Reset(&s, start);
    assert(!s.phase && s.acceleration_rpm_s == 0 && s.speed_rpm == start);
    float elapsed = 0, previous = start;
    unsigned k = 0;
    do {
        float v = tick(&s, target, dt);
        float direction = target > start ? 1.0f : -1.0f;
        assert(direction * (v - previous) >= -.002f);
        assert(v >= fminf(start,target) - .002f && v <= fmaxf(start,target) + .002f);
        previous = v; elapsed += dt;
        assert(++k < 20000U);
    } while(s.phase);
    assert(s.speed_rpm == target && s.acceleration_rpm_s == 0.0f);
    assert(fabsf(elapsed - expected_s) < dt + .002f);
    assert(tick(&s,target,.001f) == target);
}

int main(void)
{
    for(int sign=-1;sign<=1;sign+=2) {
        move(0,sign*240,.001f,1.4f);
        move(0,sign*20,.001f,2*sqrtf(.02f));
        move(sign*240,0,.003f,1.4f);
        move(sign*240,-sign*240,.007f,2.6f);
        move(0,sign*.001f,.001f,.002f);
    }
    /* Mid-ramp/plateau/fall re-target and reversal preserve acceleration,
     * including a new target inside the existing acceleration stopping arc. */
    for(unsigned when=1;when<=1399;when+=17) {
        SpeedScurve s;
        SpeedScurve_Reset(&s,0);
        for(unsigned i=0;i<when;++i) tick(&s,240,.001f);
        float target = when%2 ? -120.0f : 40.0f;
        for(unsigned i=0;i<3000;++i) {
            float v=tick(&s,target,.001f);
            assert(v>=-120.003f && v<=240.003f);
        }
        assert(s.speed_rpm==target && !s.phase && !s.acceleration_rpm_s);
    }
    /* Frequent re-targets + nonuniform real encoder dt, no unbounded work. */
    SpeedScurve s;
    SpeedScurve_Reset(&s,0);
    unsigned rng=1;
    float target=240;
    for(unsigned i=0;i<15000;++i) {
        rng=rng*1664525U+1013904223U;
        if(i%19==0) target=(float)((int)(rng%481)-240);
        float v=tick(&s,target,.0005f+(float)(rng%7)*.0002f);
        assert(fabsf(v)<=240.01f);
    }
    for(unsigned i=0;i<3000;++i) tick(&s,0,.001f);
    assert(!s.phase && s.speed_rpm==0 && s.acceleration_rpm_s==0);
    assert(SpeedScurve_Step(&s,NAN,.001f)==0);
    assert(SpeedScurve_Step(&s,240,NAN)==0);
    assert(SpeedScurve_Step(&s,240,0)==0);
    assert(SpeedScurve_Step(&s,240,-1)==0);
    assert(!s.phase && s.target_rpm==0);
    tick(&s,240,.1f);
    SpeedScurve_Reset(&s,0); /* STOP/fault/controller reset, no ramp-out lease. */
    assert(!s.phase && s.speed_rpm==0 && s.acceleration_rpm_s==0);
    tick(&s,-240,.001f);
    assert(s.speed_rpm<0); /* restart cannot apply previous positive target */

    /* Planned reference can establish the unchanged 240rpm motion admission
     * before the unchanged 1.5s no-rotation guard (not proof of real tracking). */
    TightenRundownGuard guard;
    TightenRundown_Begin(&guard);
    SpeedScurve_Reset(&s,0);
    float position=0;
    for(unsigned ms=1;ms<=1500;++ms) {
        float speed=tick(&s,240,.001f);
        position+=speed*.006f;
        if(ms%10==0) assert(!TightenRundown_Update(&guard,ms,240,speed,speed,position,.5f,1));
    }
    assert(guard.state==RUNDOWN_ARMED);
    puts("S-curve: bounds, both directions, short moves, retarget, reset, motion guard PASS");
    return 0;
}
