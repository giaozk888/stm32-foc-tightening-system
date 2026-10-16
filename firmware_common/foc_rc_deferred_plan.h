#ifndef FOC_RC_DEFERRED_PLAN_H
#define FOC_RC_DEFERRED_PLAN_H
#include <stdint.h>
#include <string.h>
#include "foc_adc_window.h"

/* Host-tested scheduling primitive only. It does NOT authorize bridge output
 * or bypass the existing current, timer, encoder and gate interlocks. A plan
 * computed from sample n may be consumed only at physical sample n+1.
 * The caller must verify live health and the actual timer preload deadline
 * before writing any CCR. Stop/fault must clear this slot immediately. */
typedef struct {
    FocWindowPlan plan;
    uint32_t source_seq;
    uint8_t valid;
} FocRcDeferredPlan;

typedef enum {
    FOC_RC_PLAN_EMPTY,
    FOC_RC_PLAN_READY,
    FOC_RC_PLAN_STALE,
    FOC_RC_PLAN_UNSAFE,
    FOC_RC_PLAN_OVERWRITE
} FocRcPlanResult;

static inline void FocRcDeferredPlan_Clear(FocRcDeferredPlan *slot)
{
    if (slot != 0) {
        slot->valid = 0U;
        slot->source_seq = 0U;
    }
}

static inline FocRcPlanResult FocRcDeferredPlan_Stage(
    FocRcDeferredPlan *slot, uint32_t source_seq, const FocWindowPlan *plan)
{
    if (slot == 0) return FOC_RC_PLAN_UNSAFE;
    if (plan == 0) {
        FocRcDeferredPlan_Clear(slot);
        return FOC_RC_PLAN_UNSAFE;
    }
    if (slot->valid) {
        FocRcDeferredPlan_Clear(slot);
        return FOC_RC_PLAN_OVERWRITE;
    }
    slot->plan = *plan;
    slot->source_seq = source_seq;
    slot->valid = 1U;
    return FOC_RC_PLAN_READY;
}

static inline FocRcPlanResult FocRcDeferredPlan_Take(
    FocRcDeferredPlan *slot, uint32_t physical_seq, uint8_t live_safe,
    FocWindowPlan *out)
{
    if (out != 0) memset(out, 0, sizeof(*out));
    if (slot == 0) return FOC_RC_PLAN_UNSAFE;
    if (out == 0) {
        FocRcDeferredPlan_Clear(slot);
        return FOC_RC_PLAN_UNSAFE;
    }
    if (!live_safe) {
        FocRcDeferredPlan_Clear(slot);
        return FOC_RC_PLAN_UNSAFE;
    }
    if (!slot->valid) return FOC_RC_PLAN_EMPTY;
    if ((uint32_t)(physical_seq - slot->source_seq) != 1U) {
        FocRcDeferredPlan_Clear(slot);
        return FOC_RC_PLAN_STALE;
    }
    *out = slot->plan;
    FocRcDeferredPlan_Clear(slot);
    return FOC_RC_PLAN_READY;
}

#endif
