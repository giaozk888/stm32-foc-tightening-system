#ifndef SPEED_ACCEL_AUDIT_H
#define SPEED_ACCEL_AUDIT_H
#include "speed_accel_feedforward.h"

/* Diagnostic-only Task evidence: first 1.5 s, 100 ms spacing. Full-rate
 * counters below observe each existing speed update, NOT the 20 kHz ISR.
 * No controller state/output is written by this module. */
#define SPEED_ACCEL_AUDIT_CAPACITY 16U
#define SPEED_ACCEL_AUDIT_SPACING_MS 100U
enum { SAA_ON=1U,SAA_SAT=2U,SAA_AW_LIMITED=4U,SAA_RELEASE=8U };
typedef struct {
    uint32_t seq,ms,trajectory_update;
    float speed_ref,speed_meas,speed_error,accel_ref;
    float iq_pi,iq_acc_ff,iq_fric,iq_raw,iq_cmd,integrator;
    uint32_t trajectory_phase,flags;
    float dt_s;
} SpeedAccelAuditFrame;
typedef struct {
    uint32_t generation,samples,trace_count,last_trace_ms,trajectory_updates;
    uint32_t sign_errors,zero_ff_errors,formula_errors,sync_errors;
    uint32_t pi_ff_opposed,sat_samples,aw_limited_samples,unexpected_aw_samples;
    uint32_t enabled_samples,first_sat_ms,start_ms;
    float max_abs_accel,max_abs_ff,max_ff_limit_ratio,saturation_s,max_abs_integrator;
    float effective_ka;
} SpeedAccelAuditMeta;
typedef struct {
    SpeedAccelAuditFrame frames[SPEED_ACCEL_AUDIT_CAPACITY];
    SpeedAccelAuditMeta meta;
} SpeedAccelAudit;
#ifdef __cplusplus
extern "C" {
#endif
void SpeedAccelAudit_Reset(SpeedAccelAudit *s);
/* Exact bounded diagnostic choices; no parsing of arbitrary float commands. */
int SpeedAccelAudit_GainPercent(const char *arg);
void SpeedAccelAudit_Push(SpeedAccelAudit *s,const SpeedAccelFfFrame *f,float friction,
    uint32_t phase,float dt,float ka,float limit,uint8_t aw_limited,uint8_t release,
    float previous_integrator,float candidate_integrator);
void SpeedAccelAudit_Log(const SpeedAccelAuditFrame *f);
#ifdef __cplusplus
}
#endif
#endif
