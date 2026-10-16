#include <assert.h>
#include <string.h>
#include "foc_rc_deferred_plan.h"

int main(void)
{
    FocRcDeferredPlan slot={0};
    FocWindowPlan in={0}, out={0};
    in.phase[0]=1001U; in.phase[1]=1002U; in.phase[2]=1003U;
    in.trigger=3500U; in.slack_ticks=50U;
    assert(FocRcDeferredPlan_Take(&slot,11U,1U,&out)==FOC_RC_PLAN_EMPTY);
    assert(out.trigger==0U);
    assert(FocRcDeferredPlan_Stage(&slot,10U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Stage(&slot,11U,&in)==FOC_RC_PLAN_OVERWRITE);
    assert(!slot.valid);
    assert(FocRcDeferredPlan_Stage(&slot,10U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Take(&slot,10U,1U,&out)==FOC_RC_PLAN_STALE);
    assert(out.trigger==0U && !slot.valid);
    assert(FocRcDeferredPlan_Stage(&slot,10U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Take(&slot,11U,1U,&out)==FOC_RC_PLAN_READY);
    assert(out.trigger==3500U && out.phase[2]==1003U && !slot.valid);
    assert(FocRcDeferredPlan_Stage(&slot,20U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Take(&slot,22U,1U,&out)==FOC_RC_PLAN_STALE);
    assert(out.trigger==0U && !slot.valid);
    assert(FocRcDeferredPlan_Stage(&slot,30U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Take(&slot,31U,0U,&out)==FOC_RC_PLAN_UNSAFE);
    assert(out.trigger==0U && !slot.valid);
    assert(FocRcDeferredPlan_Stage(&slot,UINT32_MAX,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Take(&slot,0U,1U,&out)==FOC_RC_PLAN_READY);
    assert(out.trigger==3500U && !slot.valid);
    FocRcDeferredPlan_Clear(&slot);
    assert(FocRcDeferredPlan_Stage(&slot,0U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Take(&slot,1U,1U,&out)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Stage(&slot,1U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Stage(&slot,1U,0)==FOC_RC_PLAN_UNSAFE);
    assert(!slot.valid);
    assert(FocRcDeferredPlan_Stage(&slot,1U,&in)==FOC_RC_PLAN_READY);
    assert(FocRcDeferredPlan_Take(&slot,2U,1U,0)==FOC_RC_PLAN_UNSAFE);
    assert(!slot.valid);
    return 0;
}
