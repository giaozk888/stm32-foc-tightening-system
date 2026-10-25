#ifndef ID_STEADY_STATS_H
#define ID_STEADY_STATS_H
#include "mechanical_identification.h"
/* Measurement definitions ONLY. No motor protection / model-admission changes. */
#define ID_STEADY_TARGET_RPM 600.f
#define ID_STEADY_SPEED_TOL_RPM 12.f
#define ID_STEADY_ACCEL_TOL_RPM_S 1.f
#define ID_STEADY_CONFIRM_US 500000U
#define ID_STEADY_WINDOW_US 1000000U
#define ID_STEADY_THRESHOLD_A .05f
enum { IDS_WAIT=0,IDS_WINDOW=1,IDS_DONE=2,IDS_INCOMPLETE=3 };
enum { IDS_IDREF=0,IDS_ID=1,IDS_IQ=2,IDS_IDERROR=3,IDS_RPM=4,IDS_SIGNALS=5 };
typedef struct {float integral,abs_integral,sq_integral,min,max;} IdSteadyMoment;
typedef struct {
    uint32_t total_us,run_us,max_us,episodes,samples,censored;
    uint32_t bins[4]; /* measured runs: <5ms, 5..20ms, 20..100ms, >=100ms */
} IdSteadyOver;
typedef struct {
    volatile uint32_t version;
    uint32_t state,running,frozen,stable_us,begin_us,last_us,window_us;
    uint32_t good_us,bad_us,good_n,bad_n,unstable_us,voltage_sat_us,iq_sat_us;
    uint32_t last_seq,have_seq,positive_over_us,negative_over_us;
    uint32_t filtered_good_us,filtered_bad_us;
    IdSteadyMoment signal[IDS_SIGNALS];
    IdSteadyOver raw_over,filtered_over;
    uint32_t abs_id_bins[5]; /* <=20,20..50,50..100,100..200,>200 mA */
    uint32_t dob_status_n[12]; /* [0]=valid, [1..11]=status bits 0..10; whole run */
    uint32_t max_compute_us;
} IdSteadyStats;
typedef struct {uint32_t state,good_n,good_us,bad_us,raw_us,filtered_us,max_compute_us;} IdSteadyView;
void IdSteady_Lifecycle(IdSteadyStats *s,uint8_t running,uint8_t fault);
void IdSteady_Observe(IdSteadyStats *s,uint32_t observed_us,uint32_t encoder_us,uint32_t dt_us,
    float speed_ref_rpm,float acceleration_ref_rpm_s,float speed_rpm,float id_ref,
    uint8_t iq_saturated,const MechanicalCurrent *current,uint8_t current_valid,
    float dob_abs_id_lpf,uint32_t dob_status,uint8_t dob_valid);
uint8_t IdSteady_Read(const IdSteadyStats *s,IdSteadyView *view);
#endif
