#ifndef DOB_LOAD_SPEED_CANDIDATE_H
#define DOB_LOAD_SPEED_CANDIDATE_H
#include "load_speed_policy.h"
typedef struct {
    LoadSpeedScheduler policy;
    uint32_t samples,slow_epochs,invalid_epochs,last_epoch_us;
    float base_rpm,selected_rpm;
    uint32_t phase;
} DobLoadSpeed;
typedef struct {
    uint32_t timestamp_us,reason,phase,from_slow,to_slow,valid,level,trend_valid,trend,high_us,release_us;
    float base_rpm,selected_rpm,mean_a,previous_ref_rpm,previous_accel_rpm_s;
} DobLoadSpeedEvent;
extern DobLoadSpeed dob_load_speed;
float DobLoadSpeed_Select(uint32_t encoder_us,uint32_t phase,float base,float contact,
                          float previous_ref,float previous_accel);
_Static_assert(sizeof(DobLoadSpeed)==60U,"Bounded candidate RAM");
_Static_assert(sizeof(DobLoadSpeedEvent)==64U,"First plus latest2 records in borrowed200B");
#endif
