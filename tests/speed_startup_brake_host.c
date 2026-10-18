#include <math.h>
#include <stdint.h>
#include "speed_startup_brake.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif
/* The existing SPEED-only PI policy, followed by the exact candidate kernel.
 * No position settling/active-hold branch is involved in this test harness. */
EXPORT float speed_test_step(float *integral, float ref, float speed, float dt,
                             unsigned candidate_enabled, uint32_t *flags)
{
    float error=ref-speed;
    float p=.003f*error;
    float previous=*integral;
    float next;
    unsigned bleed=(fabsf(speed)>=5.0f && fabsf(error)>=5.0f &&
        error*speed<0.0f && previous*speed>0.0f);
    if (bleed) {
        float step=5.0f*dt;
        if (previous>step) previous-=step;
        else if (previous < -step) previous+=step;
        else previous=0.0f;
        next=previous;
    } else next=previous+.020f*error*dt;
    *flags=0U;
    if (candidate_enabled) {
        SpeedStartupBrakeResult guarded=SpeedStartupBrake_Apply(
            previous,next,ref,speed,dt,5.0f,5.0f);
        next=guarded.integral_A; *flags=guarded.flags;
        if (guarded.flags&SPEED_STARTUP_I_BRAKE_RESET) bleed=1U;
    }
    if (next>.35f) next=.35f;
    if (next<-.35f) next=-.35f;
    float unsat=p+next;
    float output=unsat;
    if (output>.4f) output=.4f;
    if (output<-.4f) output=-.4f;
    if (bleed || unsat==output || (output>=.4f && error<0.0f) ||
        (output<=-.4f && error>0.0f)) *integral=next;
    return output;
}

EXPORT float speed_test_apply(float previous,float candidate,float ref,
                              float speed,float dt,uint32_t *flags)
{
    SpeedStartupBrakeResult out=SpeedStartupBrake_Apply(previous,candidate,ref,speed,dt,5,5);
    *flags=out.flags; return out.integral_A;
}
