#ifndef SPEED_SCURVE_H
#define SPEED_SCURVE_H
#include <stdint.h>

/* SPEED reference only; never a stop/fault gate or an actuator owner.
 * Units: acceleration rpm/s, jerk rpm/s^2. Existing PI/limits are unchanged. */
#define SPEED_SCURVE_MAX_ACCEL_RPM_S 200.0f
#define SPEED_SCURVE_MAX_JERK_RPM_S2 1000.0f

typedef struct {
    float speed_rpm, acceleration_rpm_s, target_rpm;
    float remaining_s, ramp_s, hold_s, jerk_rpm_s2;
    uint8_t phase;
} SpeedScurve;

void SpeedScurve_Reset(SpeedScurve *s, float reference_rpm);
float SpeedScurve_Step(SpeedScurve *s, float target_rpm, float dt_s);
#endif
