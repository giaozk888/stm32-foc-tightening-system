#ifndef SPEED_ACCEL_FEEDFORWARD_H
#define SPEED_ACCEL_FEEDFORWARD_H
#include <stdint.h>
#include "speed_pi_anti_windup.h"
#ifndef SPEED_ACCEL_FF_KA_A_PER_RPM_S
#define SPEED_ACCEL_FF_KA_A_PER_RPM_S 0.0001875f
#endif
/* Measurement criteria only, never control or protection thresholds. */
#define SPEED_ACCEL_FF_SETTLE_RATIO 0.05f
#define SPEED_ACCEL_FF_SETTLE_MIN_RPM 2.0f
#define SPEED_ACCEL_FF_SETTLE_DWELL_S 0.25f

typedef struct {
    float integral_a,iq_pi_a,iq_ff_a,iq_raw_a,iq_ref_a;
    uint8_t saturated,aw_limited;
} SpeedAccelFfResult;
typedef struct {
    uint32_t seq,ms;
    float command_rpm,speed_ref_rpm,speed_meas_rpm,accel_ref_rpm_s;
    float iq_pi_a,iq_ff_a,iq_raw_a,iq_ref_a,speed_integrator_a,iq_meas_a;
    uint8_t enabled,saturated,valid,reserved;
} SpeedAccelFfFrame;
typedef struct {
    uint32_t samples,segment;
    float time_s,max_error_rpm,accel_error_integral,accel_time_s;
    float decel_error_integral,decel_time_s,overshoot_rpm,iq_peak_a,integrator_peak_a,iq_measured_peak_a;
    float saturation_s,saturation_run_s,saturation_run_max_s;
    float command_rpm,direction,segment_time_s,settle_candidate_s,settling_time_s;
    uint8_t settling,settled,reserved[2];
} SpeedAccelFfStats;

#ifdef __cplusplus
extern "C" {
#endif
SpeedAccelFfResult SpeedAccelFf_Apply(float previous,float candidate,float p,
    float accel_ref,float ka,float iq_limit,float integral_limit,uint8_t release,uint8_t enabled);
void SpeedAccelFf_StatsReset(SpeedAccelFfStats *s);
void SpeedAccelFf_Observe(SpeedAccelFfStats *s,const SpeedAccelFfFrame *f,float dt_s);
void SpeedAccelFf_Log(const SpeedAccelFfFrame *f);
#ifdef __cplusplus
}
#endif
#endif
