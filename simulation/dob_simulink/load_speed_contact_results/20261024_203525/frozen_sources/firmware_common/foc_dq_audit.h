#ifndef FOC_DQ_AUDIT_H
#define FOC_DQ_AUDIT_H
#include "foc_dq_decoupling.h"

/* Classification/evidence ONLY: none of these values affects a stop gate. */
#define DQ_AUDIT_STATIONARY_RPM 1.0f
#define DQ_AUDIT_STARTUP_US 500000U
#define DQ_AUDIT_LOG_US 100000U
enum { DQA_ON=1U,DQA_RUNNING=2U,DQA_STARTUP=4U,DQA_STATIONARY=8U,
       DQA_CRUISE=16U,DQA_SATURATED=32U };
typedef struct {
    uint32_t seq,us,elapsed_us,flags;
    float mech_rpm,we_rad_s,id,iq,vd_pi,vq_pi,vd_dec,vq_dec,vd_cmd,vq_cmd;
    float speed_ref,speed_meas;
} FocDqAuditFrame;
typedef struct {
    uint32_t samples,run_n,zero_n,start_n,cruise_n,sat_n,first_sat_us;
    uint32_t nominal_d_bad,nominal_q_bad,config_bad,invalid_n,started,start_us;
    float zero_d_max,zero_q_max,start_d_max,start_q_max,cruise_d_sum,cruise_q_sum;
    float we_abs_max,we_chain_error_max;
} FocDqAuditStats;
typedef struct { FocDqAuditFrame latest; FocDqAuditStats stats; } FocDqAudit;

#ifdef __cplusplus
extern "C" {
#endif
/* Accepted ADC/PI frames only. Ordinary Flash text, NOT added to RAM hot code.
 * Fixed arithmetic, no formatting, allocation, HAL, RTOS, loop or power writes. */
void FocDqAudit_Record(volatile FocDqAudit *audit,const FocDqAuditFrame *frame);
/* MonitorTask only, official tokenized payloads <=32 B per row. */
void FocDqAudit_LogFrame(const FocDqAuditFrame *frame);
void FocDqAudit_LogStats(const FocDqAuditStats *stats);
#ifdef __cplusplus
}
#endif
#endif
