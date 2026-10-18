#include "speed_bumpless.h"
#include "speed_startup_brake_host.c" /* Keep the historical SB1 comparison exact. */

EXPORT float bumpless_apply(float previous,float candidate,float ref,float speed,
                            float dt,uint32_t *flags)
{
    SpeedStartupBrakeResult out=SpeedBumpless_Apply(previous,candidate,ref,speed,dt,5,5);
    *flags=out.flags; return out.integral_A;
}

/* Same SPEED-only staging as the production call site. The old bleed mutates
 * its candidate, but SB2 must calculate from the captured PRE-bleed integral. */
EXPORT float bumpless_step(float *integral,float ref,float speed,float dt,uint32_t *flags)
{
    float before=*integral;
    float error=ref-speed;
    float candidate=before+.020f*error*dt;
    unsigned bleed=(fabsf(speed)>=5 && fabsf(error)>=5 && error*speed<0 && before*speed>0);
    if (bleed) {
        float step=5.0f*dt;
        candidate=before>step ? before-step : before < -step ? before+step : 0;
    }
    SpeedStartupBrakeResult out=SpeedBumpless_Apply(before,candidate,ref,speed,dt,5,5);
    candidate=fmaxf(-.35f,fminf(.35f,out.integral_A));
    *flags=out.flags;
    if (out.flags&SPEED_BUMPLESS_UNLOAD) bleed=1;
    float unsat=.003f*error+candidate;
    float iq=fmaxf(-.4f,fminf(.4f,unsat));
    if (bleed || unsat==iq || (iq>=.4f && error<0) || (iq<=-.4f && error>0))
        *integral=candidate;
    return iq;
}
