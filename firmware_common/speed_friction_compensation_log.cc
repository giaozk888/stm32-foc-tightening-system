#define PW_LOG_MODULE_NAME "FRICTION"
#include "speed_friction_compensation.h"
#include "pw_log/log.h"
extern "C" void SpeedFriction_Log(const SpeedFrictionFrame *f)
{
    const SpeedAccelFfFrame *c=&f->control;
    /* Three bounded tokens, not a >32B message silently truncated. Task only. */
    PW_LOG_INFO("FRC R seq=%u ms=%u on=%u ff_on=%u speed_ref=%.3f speed_meas=%.3f accel_ref=%.3f command=%.3f",
        unsigned(c->seq),unsigned(c->ms),unsigned(f->enabled),unsigned(c->enabled),
        c->speed_ref_rpm,c->speed_meas_rpm,c->accel_ref_rpm_s,c->command_rpm);
    PW_LOG_INFO("FRC C seq=%u sat=%u iq_pi=%.6f iq_acc_ff=%.6f iq_fric=%.6f iq_raw=%.6f iq_ref=%.6f",
        unsigned(c->seq),unsigned(c->saturated),c->iq_pi_a,c->iq_ff_a,f->iq_fric_a,c->iq_raw_a,c->iq_ref_a);
    PW_LOG_INFO("FRC I seq=%u speed_integrator=%.6f iq_meas=%.6f",
        unsigned(c->seq),c->speed_integrator_a,c->iq_meas_a);
}
