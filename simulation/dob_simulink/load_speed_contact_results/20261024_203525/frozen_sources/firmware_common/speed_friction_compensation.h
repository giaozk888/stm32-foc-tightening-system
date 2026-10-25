#ifndef SPEED_FRICTION_COMPENSATION_H
#define SPEED_FRICTION_COMPENSATION_H
#include "speed_accel_feedforward.h"
#ifndef SPEED_FRICTION_I_A
#define SPEED_FRICTION_I_A 0.20f
#endif
#ifndef SPEED_FRICTION_DEADBAND_RPM
#define SPEED_FRICTION_DEADBAND_RPM 2.0f
#endif
/* Evidence definitions only: not controller/protection parameters. */
#define SPEED_FRICTION_LOW_SPEED_RPM 30.0f
#define SPEED_FRICTION_MOTION_RPM 2.0f
#define SPEED_FRICTION_MOTION_CONFIRM_S 0.05f

typedef struct { SpeedAccelFfResult speed; float iq_fric_a; } SpeedFrictionResult;
typedef struct {
    SpeedAccelFfFrame control;
    float iq_fric_a;
    uint8_t enabled,reserved[3];
} SpeedFrictionFrame;
typedef struct {
    uint32_t samples;
    float elapsed_s,low_error_integral,low_time_s,cruise_error_integral,cruise_time_s;
    float integrator_peak_a,pi_peak_a,iq_peak_a,iq_measured_peak_a;
    float speed_integral,wrong_direction_time_s,start_delay_s;
} SpeedFrictionDirectionStats;
typedef struct {
    SpeedFrictionDirectionStats positive,negative;
    float command_rpm,segment_elapsed_s,motion_good_s;
    uint8_t initialized,moving,reserved[2];
} SpeedFrictionStats;
#ifdef __cplusplus
extern "C" {
#endif
SpeedFrictionResult SpeedFriction_Apply(float previous,float candidate,float p,
    float accel_ref,float ka,float speed_ref,float friction_a,float deadband,
    float iq_limit,float integral_limit,uint8_t release,uint8_t accel_enabled,uint8_t enabled);
void SpeedFriction_StatsReset(SpeedFrictionStats *s);
void SpeedFriction_Observe(SpeedFrictionStats *s,const SpeedFrictionFrame *f,float dt_s);
void SpeedFriction_Log(const SpeedFrictionFrame *f);
#ifdef __cplusplus
}
#endif
#endif
