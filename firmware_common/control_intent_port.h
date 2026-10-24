#ifndef CONTROL_INTENT_PORT_H
#define CONTROL_INTENT_PORT_H
#include "control_intent.h"
#include <math.h>
/* This adapter passes intent targets, not trajectory ticks, to the backend.
 * The backend owns its reference generator (legacy ramp, or opt-in SPEED
 * S-curve), parameters and mode-entry resets. Never ramp here a second time.
 * No arbitrary dynamic gain/limit setter. */
typedef struct {
    void (*idle)(void *);
    void (*speed)(void *,float);
    void (*position)(void *,float);
    void (*iq)(void *,float);
    void (*stop)(void *);
    void *context;
    float speed_iq_limit_a,direct_iq_limit_a,speed_limit_rpm;
    ControlIntentMode last_mode;
} ControlIntentPort;
static inline int ControlIntent_Apply(ControlIntentPort *p,const ControlIntent *i)
{
    if (!p || !i || !p->idle || !p->speed || !p->iq || !p->stop) return 0;
    if (!isfinite(i->position_target) || !isfinite(i->speed_target_rpm) || !isfinite(i->iq_target_a) ||
        !isfinite(i->iq_limit_a) || !isfinite(i->speed_limit_rpm) || i->hold_integrators ||
        i->iq_limit_a<0 || i->speed_limit_rpm<0 || i->speed_limit_rpm>p->speed_limit_rpm) return 0;
    /* Current candidate only requests integral reset on mode entry. Position
     * controller is P-only; speed reset uses existing backend mode reset.
     * Same-mode reset/active hold is deliberately unsupported, not ignored. */
    if ((i->reset_position_integrator || i->reset_speed_integrator) &&
            p->last_mode==i->control_mode && i->control_mode!=CONTROL_OFF &&
            i->control_mode!=CONTROL_NEUTRAL) return 0;
    switch (i->control_mode) {
    case CONTROL_OFF:
        if (i->enable_current_loop || i->enable_speed_loop || i->enable_position_loop) return 0;
        p->stop(p->context); p->idle(p->context); break;
    case CONTROL_NEUTRAL:
        if (!i->enable_current_loop || i->enable_speed_loop || i->enable_position_loop ||
                i->iq_target_a!=0 || i->speed_target_rpm!=0) return 0;
        p->idle(p->context); break;
    case CONTROL_SPEED:
        if (!i->enable_current_loop || !i->enable_speed_loop || i->enable_position_loop ||
                i->iq_limit_a!=p->speed_iq_limit_a || fabsf(i->speed_target_rpm)>i->speed_limit_rpm) return 0;
        p->speed(p->context,i->speed_target_rpm); break;
    case CONTROL_IQ:
        if (!i->enable_current_loop || i->enable_speed_loop || i->enable_position_loop ||
                i->iq_limit_a!=p->direct_iq_limit_a || fabsf(i->iq_target_a)>i->iq_limit_a) return 0;
        p->iq(p->context,i->iq_target_a); break;
    case CONTROL_POSITION:
        /* Reserved: do not pretend per-intent position limits are enforced
         * by the legacy controller before that contract is implemented. */
        return 0;
    default: return 0;
    }
    p->last_mode=i->control_mode; return 1;
}
#endif
