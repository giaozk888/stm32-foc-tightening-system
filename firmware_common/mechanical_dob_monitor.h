#ifndef MECHANICAL_DOB_MONITOR_H
#define MECHANICAL_DOB_MONITOR_H
#include "mechanical_dob_shadow.h"
#include "mechanical_identification.h"
#if defined(FOC_DOB_CONTACT20_OBSERVE10)
#include "dob_contact20_observe10.h"
#endif
#if defined(FOC_DOB_SPIKE_ADMISSION)
#include "dob_current_admission.h"
#endif
#define DOB_MONITOR_CAPACITY 16U
#define DOB_MONITOR_RECORD_US 64000U
#define DOB_MONITOR_CURRENT_TAU_S .020f
/* Model-domain admission only, NEVER motor IdRef/current/hard-OC limit.
 * User-selected 60mA applies only to the new direct100 diagnostic candidate. */
#if defined(FOC_DOB_DIRECT_JUMP_REJECT)
#define DOB_MONITOR_MAX_FILTERED_ABS_ID_A .060f
#else
#define DOB_MONITOR_MAX_FILTERED_ABS_ID_A .05f
#endif
enum {
    DOB_MONITOR_OFF=32U, DOB_MONITOR_TIME=64U, DOB_MONITOR_SATURATED=128U,
    DOB_MONITOR_ID=256U, DOB_MONITOR_SEQUENCE=512U, DOB_MONITOR_CURRENT=1024U
};
typedef struct {
    uint32_t sample_us,adc_seq,adc_source_us,adc_published_us,status,valid;
    float omega_rad_s,iq_a,iq_matched_a,id_a,disturbance_a;
} MechanicalDobMonitorFrame;
typedef struct {
    MechanicalDobShadow observer;
    MechanicalDobMonitorFrame frames[DOB_MONITOR_CAPACITY],current;
    volatile uint32_t version;
    uint32_t head,count,observations,valid_samples,rejected_samples;
    uint32_t last_seq,last_encoder_us,last_stored_us,running,frozen,have_sample;
    float iq_lpf,abs_id_lpf,disturbance_abs_peak,positive_sum,negative_sum;
    uint32_t positive_n,negative_n,max_compute_us;
} MechanicalDobMonitor;
typedef struct {
    MechanicalDobMonitorFrame current;
    uint32_t running,frozen,observations,valid_samples,rejected_samples,max_compute_us;
    float disturbance_abs_peak,positive_mean,negative_mean,abs_id_lpf;
} MechanicalDobMonitorView;

/* Frozen, qualified bidirectional candidate. No setter / persistence API. */
extern const MechanicalNormalizedModel mechanical_dob_identified_model;
#if defined(FOC_DOB_NORMAL_CONTROL)
/* Task writer only; preserve seqlock version while clearing old-session data. */
void MechanicalDobMonitor_Rearm(MechanicalDobMonitor *s);
#endif
void MechanicalDobMonitor_Lifecycle(MechanicalDobMonitor *s,uint8_t running,uint8_t fault);
void MechanicalDobMonitor_Observe(MechanicalDobMonitor *s,uint32_t observed_us,
    uint32_t encoder_us,uint32_t dt_us,float omega_rad_s,uint8_t iq_saturated,
    const MechanicalCurrent *current,uint8_t current_valid);
uint8_t MechanicalDobMonitor_Read(const MechanicalDobMonitor *s,MechanicalDobMonitorView *view);
#endif
