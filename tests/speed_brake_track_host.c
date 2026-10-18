/* Actual candidate and exact SB2 predecessor, no devices or plant model. */
#include "speed_brake_track.h"
#include "speed_bumpless_host.c"

EXPORT void brake_reset(SpeedBrakeTrack *state) { SpeedBrakeTrack_Reset(state); }
EXPORT float brake_apply(SpeedBrakeTrack *state,float ref,float filtered,float instant,
                         float *integral,float current,uint32_t *limited)
{
    SpeedBrakeTrackResult out=SpeedBrakeTrack_Apply(state,ref,filtered,instant,
        .003f*(ref-filtered),*integral,current,.003f,5,5,.4f,.35f);
    *limited=out.limited; *integral=out.integral_A; return out.current_A;
}
EXPORT float brake_step(SpeedBrakeTrack *state,float *integral,float ref,
                        float filtered,float instant,float dt,uint32_t *limited)
{
    uint32_t sb2_flags;
    float iq=bumpless_step(integral,ref,filtered,dt,&sb2_flags);
    return brake_apply(state,ref,filtered,instant,integral,iq,limited);
}
