#ifndef CONTROL_INTENT_H
#define CONTROL_INTENT_H
#include <stdint.h>

typedef enum { CONTROL_OFF, CONTROL_NEUTRAL, CONTROL_POSITION,
               CONTROL_SPEED, CONTROL_IQ } ControlIntentMode;
/* References/constraints only. No controller state, gain or PWM registers. */
typedef struct {
    ControlIntentMode control_mode;
    float position_target, speed_target_rpm, iq_target_a;
    float iq_limit_a, speed_limit_rpm;
    uint8_t enable_position_loop, enable_speed_loop, enable_current_loop;
    uint8_t reset_position_integrator, reset_speed_integrator, hold_integrators;
} ControlIntent;

typedef struct {
    float position_deg, speed_rpm, acceleration_rpm_s, iq_a, id_a;
    uint32_t timestamp_us;
} ControlFeedback;
typedef struct { ControlIntent reference; float acceleration_rpm_s; } TrajectoryReference;
/* Reserved contracts, not installed or executed by this candidate.
 * Trajectory owns time shaping; compensation owns additive contributions;
 * anti-windup belongs to the controller, never the process FSM. */
typedef struct {
    void (*trajectory_generator)(void *,const ControlIntent *,const ControlFeedback *,TrajectoryReference *);
    float (*friction_feedforward)(void *,const TrajectoryReference *,const ControlFeedback *);
    float (*acceleration_feedforward)(void *,const TrajectoryReference *,const ControlFeedback *);
    void (*speed_anti_windup)(void *,float requested_iq,float applied_iq,float dt_s);
    void (*dq_decoupling)(void *,const ControlFeedback *,float *vd_ff,float *vq_ff);
    float (*dob)(void *,const TrajectoryReference *,const ControlFeedback *);
    void *context;
} ControlAlgorithmExtensions;

/* Identity boundary only; existing backend's ramp and PIs remain unchanged. */
static inline TrajectoryReference ControlIntent_Passthrough(ControlIntent intent)
{ return (TrajectoryReference){intent,0.0f}; }
#endif
