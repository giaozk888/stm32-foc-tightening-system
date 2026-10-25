#ifndef KA_IDENTIFICATION_H
#define KA_IDENTIFICATION_H
#include "speed_accel_feedforward.h"
/* Passive MotorControlTask observer; no ISR, controller or protection writes. */
#define KA_IDENT_CAPACITY 24U
#define KA_IDENT_WINDOW_US 100000U
#define KA_IDENT_MAX_GAP_US 5000U
enum { KAI_BAD_INPUT=1U, KAI_SATURATED=2U, KAI_CURRENT_STALE=4U,
       KAI_SAMPLE_GAP=8U, KAI_ENCODER_STALE=16U };
typedef struct {
    uint32_t seq,start_us,end_us,flags;
    float speed_start_rpm,speed_end_rpm,mean_iq_a,mean_friction_a;
    float mean_speed_ref_rpm,mean_speed_meas_rpm;
} KaIdentFrame;
typedef struct {
    KaIdentFrame frames[KA_IDENT_CAPACITY];
    uint32_t generation,count,samples,start_us,last_us,last_seq,last_adc_count,flags,started;
    float start_speed,last_speed,last_iq,last_friction,last_ref;
    float iq_integral,friction_integral,ref_integral,speed_integral;
} KaIdentification;
#ifdef __cplusplus
extern "C" {
#endif
void KaIdent_Reset(KaIdentification *s);
void KaIdent_Observe(KaIdentification *s,const SpeedAccelFfFrame *f,float friction,
    uint32_t now_us,uint32_t encoder_us,uint32_t accepted_adc_count);
void KaIdent_Log(const KaIdentFrame *f);
#ifdef __cplusplus
}
#endif
#endif
