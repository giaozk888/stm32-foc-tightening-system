#ifndef DOB_LOAD_SPEED_CANDIDATE_H
#define DOB_LOAD_SPEED_CANDIDATE_H
#include "load_speed_policy.h"
#if defined(FOC_DOB_LOAD_SPEED_CONTACT_HOLD)
#include "load_speed_contact_hold.h"
#endif
typedef struct {
    LoadSpeedScheduler policy;
    uint32_t samples,slow_epochs,invalid_epochs,last_epoch_us;
    float base_rpm,selected_rpm;
    uint32_t phase;
#if defined(FOC_DOB_LOAD_SPEED_CONTACT_HOLD)
    uint32_t contact_held,reacquire_us;
#endif
} DobLoadSpeed;
#if defined(FOC_DOB_LOAD_SPEED_CONTACT_HOLD)
typedef struct {
    uint32_t timestamp_us,reason,phase,flags,high_us,release_us;
    float base_rpm,selected_rpm,mean_a,previous_ref_rpm,previous_accel_rpm_s;
    uint32_t sample_index;
} DobLoadSpeedEvent;
#define DLS_EVENT_BYTES 48U
#define DLS_EVENT_SLOTS 4U
#define DLS_TRACE_MAGIC 0xD1500002U
#else
typedef struct {
    uint32_t timestamp_us,reason,phase,from_slow,to_slow,valid,level,trend_valid,trend,high_us,release_us;
    float base_rpm,selected_rpm,mean_a,previous_ref_rpm,previous_accel_rpm_s;
} DobLoadSpeedEvent;
#define DLS_EVENT_BYTES 64U
#define DLS_EVENT_SLOTS 3U
#define DLS_TRACE_MAGIC 0xD1500001U
#endif
extern DobLoadSpeed dob_load_speed;
float DobLoadSpeed_Select(uint32_t encoder_us,uint32_t phase,float base,float contact,
                          float previous_ref,float previous_accel);
#if defined(FOC_DOB_LOAD_SPEED_CONTACT_HOLD)
_Static_assert(sizeof(DobLoadSpeed)==68U,"Bounded contact-hold candidate RAM");
#else
_Static_assert(sizeof(DobLoadSpeed)==60U,"Bounded candidate RAM");
#endif
_Static_assert(sizeof(DobLoadSpeedEvent)==DLS_EVENT_BYTES,"Trace ABI");
_Static_assert(8U+DLS_EVENT_SLOTS*DLS_EVENT_BYTES==200U,"Borrowed tail ownership");
#endif
