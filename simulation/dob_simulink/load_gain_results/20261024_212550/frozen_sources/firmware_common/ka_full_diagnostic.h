#ifndef KA_FULL_DIAGNOSTIC_H
#define KA_FULL_DIAGNOSTIC_H
#include "ka_sync_diagnostic.h"
#define KA_FULL_CAPACITY 240U
#define KA_FULL_BIN_US 10000U
/* Each point summarizes ALL task observations in a ~10ms bin. No UART stream,
 * no control feedback. Source clock semantics are identical to KaSync. */
typedef struct {
    uint16_t interval_us,task_age_us;
    int16_t current_relative_us;
    uint16_t adc_seq_step;
    int16_t raw_delta,iq_mean_0p1ma,friction_mean_0p1ma,net_lpf_mean_0p1ma;
    int16_t speed_0p01rpm,reference_0p01rpm,accel_ref_0p1rpm_s;
    uint8_t samples,flags;
} KaFullPoint;
typedef struct {
    KaFullPoint points[KA_FULL_CAPACITY];
    uint32_t generation,count,observations,begin_us,first_encoder_us,last_encoder_us;
    uint32_t first_adc_seq,last_adc_seq,read_failures,flags,active,publish_cycles_max;
    float first_speed,first_ref,net_lpf,prev_iq;
    uint32_t bin_start_us,bin_seq,last_observe_us,last_observe_seq,interval_samples,interval_flags;
    float duration_s,iq_integral,friction_integral,net_integral;
    int32_t raw_sum;
    uint16_t first_raw,reserved;
} KaFullDiagnostic;
void KaFull_Reset(KaFullDiagnostic *s);
void KaFull_Observe(KaFullDiagnostic *s,uint32_t now,uint32_t encoder_us,uint32_t dt_us,
    uint16_t raw,int32_t raw_delta,float speed,float reference,float accel_ref,float friction,
    uint8_t saturated,const KaSyncCurrent *current,uint8_t valid);
#endif
