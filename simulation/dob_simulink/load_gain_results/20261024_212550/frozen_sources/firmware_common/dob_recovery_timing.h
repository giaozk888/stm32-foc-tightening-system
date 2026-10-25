#ifndef DOB_RECOVERY_TIMING_H
#define DOB_RECOVERY_TIMING_H
#include "dob_trend_shadow.h"
/* Passive task diagnostics only. The 75-point classifier never reads its
 * final25 value/stamp slots. Borrow200 bytes there, without changing the ABI.
 * Three48-byte completed records + one48-byte pending record; no type punning. */
enum { DRT_READY,DRT_LOW,DRT_QUALIFY,DRT_WARM,DRT_QUALITY,DRT_WINDOW,DRT_LEVEL,DRT_TREND,DRT_OTHER };
enum { DRT_COMPLETE=1U<<16,DRT_STOPPED=1U<<17,DRT_CLOCK_UNCERTAIN=1U<<18,DRT_INITIAL=1U<<19,
       DRT_CLASS_RESET=1U<<20,DRT_MULTIPLE_RESETS=1U<<21 };
typedef struct {
    uint32_t start_us,end_us,low_us,qualify_us,warm_us,quality_us;
    uint32_t window_us,level_us,trend_us,other_us,warm_credit_us,flags_reason;
} DobRecoveryRecord;
typedef struct {
    uint32_t abi,calls,records,overwritten,short_gaps,active;
    uint32_t last_us,phase,warm_us,clock_errors,completed,interrupted;
    uint32_t last_classifier_resets,pending_first_invalid_us,first_invalid_us[3];
} DobRecoveryTiming;
extern DobRecoveryTiming dob_recovery_timing;
void DobRecovery_Observe(DobTrendClassifier *classifier,const DobTrendInput *input,
    uint32_t status,float omega,uint32_t armed,float warm_elapsed_s);
void DobRecovery_Read(const DobTrendClassifier *classifier,uint32_t slot,DobRecoveryRecord *record);
_Static_assert(sizeof(DobRecoveryRecord)==48U,"Recovery record ABI");
_Static_assert(sizeof(DobRecoveryTiming)==68U,"Recovery audit bounded RAM");
#endif
