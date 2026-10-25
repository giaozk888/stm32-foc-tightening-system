#ifndef STARTUP_TIMESTAMPS_H
#define STARTUP_TIMESTAMPS_H
#include <stdint.h>
/* Evidence thresholds only. They NEVER gate control or protection. */
#ifndef STARTUP_IQ_THRESHOLD_A
#define STARTUP_IQ_THRESHOLD_A 0.010f
#endif
#ifndef STARTUP_MOTION_MIN_COUNTS
#define STARTUP_MOTION_MIN_COUNTS 16U
#endif
#ifndef STARTUP_MOTION_MIN_FORWARD_SAMPLES
#define STARTUP_MOTION_MIN_FORWARD_SAMPLES 4U
#endif
#ifndef STARTUP_MOTION_CONFIRM_US
#define STARTUP_MOTION_CONFIRM_US 10000U
#endif
#ifndef STARTUP_MOTION_WINDOW_US
#define STARTUP_MOTION_WINDOW_US 50000U
#endif
#ifndef STARTUP_MOTION_REVERSE_TOL_COUNTS
#define STARTUP_MOTION_REVERSE_TOL_COUNTS 2U
#endif
#ifndef STARTUP_MOTION_MAX_FORWARD_GAP_US
#define STARTUP_MOTION_MAX_FORWARD_GAP_US 5000U
#endif
#ifndef STARTUP_SPEED_THRESHOLD_RPM
#define STARTUP_SPEED_THRESHOLD_RPM 2.0f
#endif
enum { START_T0=1U,START_IQ=2U,START_MOTION=4U,START_SPEED=8U,START_STABLE=16U };
typedef struct {
    uint32_t valid,t0_us,t_iq_us,t_motion_us,t_speed_us,t_stable_us;
    uint32_t motion_begin_us,observations,last_sample_us,candidate_us;
    uint32_t forward_samples,forward_counts,reverse_counts,sample_valid;
    uint32_t last_forward_us;
    int32_t motion_direction;
    float direction,iq_at_event_a,speed_at_event_rpm;
} StartupTimestamps;
#ifdef __cplusplus
extern "C" {
#endif
void StartupTimes_Reset(StartupTimestamps *s);
void StartupTimes_Begin(StartupTimestamps *s,uint32_t now_us,float command_rpm);
void StartupTimes_Observe(StartupTimestamps *s,uint32_t now_us,uint32_t sample_us,
    int32_t mechanical_delta_counts,float speed_meas_rpm,float iq_cmd_a);
void StartupTimes_Stable(StartupTimestamps *s,uint32_t now_us);
void StartupTimes_Log(const StartupTimestamps *s);
#ifdef __cplusplus
}
#endif
#endif
