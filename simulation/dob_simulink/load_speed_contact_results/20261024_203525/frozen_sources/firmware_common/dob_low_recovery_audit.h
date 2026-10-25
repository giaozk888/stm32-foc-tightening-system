#ifndef DOB_LOW_RECOVERY_AUDIT_H
#define DOB_LOW_RECOVERY_AUDIT_H
#include <stdint.h>
/* Two96-byte snapshots plus ABI/count8-byte footer in window75's unused tail.
 * First/last of one supervised session. Routine classifier clear preserves
 * that tail; a new recorder bind/session clears it. No control API. */
typedef struct {
    uint32_t timestamp_us,reason,site,mode,status,input_valid,filter_updated;
    uint32_t decision,quality_reason,quiet_n,quiet_age_us,low_start_us,return_start_us;
    uint32_t low_elapsed_us,return_elapsed_us,source_us,published_us,accepted_gap_us;
    float omega_rad_s,id_a,iq_a,abs_id_lpf_a,omega_range_rad_s,drive_range_a;
} DobLowRecoveryEvent;
enum { DLR_LOG_SOURCE=1,DLR_LOG_DIRECTION,DLR_LOG_LONG,DLR_LOG_RELOW,
       DLR_LOG_REBASED_SAT,DLR_LOG_COLD_READY,DLR_LOG_TIMEOUT,DLR_LOG_LIFECYCLE };
_Static_assert(sizeof(DobLowRecoveryEvent)==96U,"Two snapshots fit borrowed200-byte tail");
void DobLowAudit_Record(const void *recovery,const void *monitor,uint32_t enc,
                       float omega,uint32_t input_valid,uint32_t reason,uint32_t site);
#endif
