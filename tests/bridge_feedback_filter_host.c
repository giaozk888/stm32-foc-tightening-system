#include <assert.h>
#include <stdio.h>
#include "bridge_feedback_filter_core.h"
static BridgeFeedbackFilter s;
static void begin(void) { assert(BridgeFilter_Begin(&s,1560,1560,3300)); }
static void push(uint16_t u,uint16_t v,unsigned t)
{ BridgeFilter_Push(&s,u,v,t); }
int main(void)
{
    begin();
    for (unsigned i=1;i<=1000;i++) push(1560,1560,i*50U-10U);
    assert(s.pairs==1000 && s.protection.feedback_pairs==997);
    assert(s.protection.result==FOC_OC_CLEAR && s.protection.repaired_pairs==0);
    assert(BridgeFilter_Push(&s,1560,1560,50040U)==FOC_OC_TRIPPED);
    begin(); push(1560,1560,40); push(1560,1560,90); push(1560,1560,140);
    push(2200,1560,190); push(1560,1560,240); push(1560,1560,290);
    assert(s.protection.repaired_pairs==1 && s.protection.result!=FOC_OC_TRIPPED);
    begin();
    for (unsigned i=1;i<=8;i++) push(i<5?1560:2200,1560,i*50);
    assert(s.protection.reason==FOC_FP_CONFIRMED_CURRENT);
    assert(BridgeFilter_Push(&s,1560,1560,450)==FOC_OC_TRIPPED); /* sticky */
    begin(); push(4096,1560,40); assert(s.protection.reason==FOC_FP_RAW_INVALID);
    begin(); push(1560,1560,40); push(1560,1560,140);
    assert(s.protection.reason==FOC_FP_SEQUENCE);
    begin(); assert(FocFp_Poll(&s.protection,100,0)!=FOC_OC_TRIPPED);
    assert(FocFp_Poll(&s.protection,101,0)==FOC_OC_TRIPPED);
    begin(); assert(FocFp_Poll(&s.protection,25,FOC_FP_HW_TRIP)==FOC_OC_TRIPPED);
    assert(!BridgeFilter_Begin(&s,1560,1560,2999));
    begin();
    for (unsigned i=1;i<=45 && s.protection.result!=FOC_OC_TRIPPED;i++)
        push(i%4==0?2200:1560,1560,i*50U);
    assert(s.protection.reason==FOC_FP_REPAIR_BUDGET);
    puts("BRIDGE FILTER PASS: 1000 pairs, isolated/persistent, raw validity, gap, timeout, sticky, budget");
}
