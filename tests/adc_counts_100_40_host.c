/* Synthetic boundary and independent safety tests; not the missing real trace. */
#include <assert.h>
#include <stdio.h>
#include "foc_feedback_safety_candidate.h"

_Static_assert(FOC_CURRENT_JUMP_THRESHOLD_COUNTS==100U,"jump");
_Static_assert(FOC_CURRENT_RETURN_TOL_COUNTS==40U,"return");
_Static_assert(FOC_CURRENT_CONFIRM_TOL_COUNTS==25U,"confirm unchanged");
_Static_assert(FOC_CURRENT_UNRESOLVED_LIMIT==3U,"unresolved unchanged");
static FocCurrentValidation v;
static void begin(void) { FocCurrentValidation_Begin(&v,1560,1560); }
static FocFeedbackSafety safety;
static uint32_t seq,now;
static void safety_begin(void)
{
    seq=now=0;
    FocFeedbackSafetyConfig c={.protection={4.0f,100U,100U,6U,4U},
        .zero_u=1560,.zero_v=1560,.count_to_A=3300.0f/(4095.0f*120.0f)};
    assert(FocFeedbackSafety_Begin(&safety,c,0)==FOC_OC_CLEAR);
    assert(safety.raw_trip_counts==595U);
}
static int push(uint16_t u,uint16_t w)
{
    now+=50; ++seq;
    FocFeedbackFrame frame;
    FocOcConfirmResult r=FocFeedbackSafety_Push(&safety,seq,now,u,w,.25f,0,1);
    int use=FocFeedbackSafety_Take(&safety,now,0,1,&frame);
    return r==FOC_OC_TRIPPED ? -1 : use;
}
int main(void)
{
    /* Inclusive +/-100 boundary, and 101 starts suspicion in either channel. */
    begin(); assert(FocCurrentValidation_Push(&v,1660,1460)==1);
    assert(!v.current_suspect_total && v.reference.u==1660 && v.reference.v==1460);
    begin(); assert(FocCurrentValidation_Push(&v,1661,1560)==0);
    assert(v.state==FOC_CURRENT_SUSPECT && v.reference.u==1560 && !v.current_unresolved_consecutive);
    assert(FocCurrentValidation_Push(&v,1600,1520)==1); /* old distance exactly 40 */
    assert(v.current_confirmed_spike==1 && !v.current_unresolved_consecutive);
    begin(); assert(FocCurrentValidation_Push(&v,1661,1560)==0);
    assert(FocCurrentValidation_Push(&v,1601,1560)==0); /* 41 from old, not nearer candidate */
    assert(v.current_unresolved_consecutive==1 && v.reference.u==1560);
    assert(FocCurrentValidation_Push(&v,1560,1560)==1);
    assert(!v.current_unresolved_consecutive && v.current_recovered_after_unresolved==1);
    begin(); assert(FocCurrentValidation_Push(&v,1459,1560)==0);
    assert(FocCurrentValidation_Push(&v,1520,1600)==1 && v.current_confirmed_spike==1);
    begin(); assert(FocCurrentValidation_Push(&v,1560,1661)==0);
    assert(v.reference.u==1560 && v.reference.v==1560);
    assert(FocCurrentValidation_Push(&v,1561,1600)==1 && v.reference.u==1561 && v.reference.v==1600);

    /* Stable confirmation remains 25; inward 26 is not a valid outward ramp. */
    begin(); assert(FocCurrentValidation_Push(&v,1700,1560)==0);
    assert(FocCurrentValidation_Push(&v,1675,1560)==1 && v.current_confirmed_transition==1);
    begin(); assert(FocCurrentValidation_Push(&v,1700,1560)==0);
    assert(FocCurrentValidation_Push(&v,1674,1560)==0 && v.current_unresolved_consecutive==1);
    /* Existing outward-ramp branch shares JUMP: now <=100, not <=60. */
    begin(); assert(FocCurrentValidation_Push(&v,1700,1560)==0);
    assert(FocCurrentValidation_Push(&v,1800,1560)==1 && v.current_confirmed_transition==1);
    begin(); assert(FocCurrentValidation_Push(&v,1700,1560)==0);
    assert(FocCurrentValidation_Push(&v,1801,1560)==0 && v.current_unresolved_consecutive==1);

    /* Widening does not permanently swallow incoherent data or clear a fault. */
    begin(); assert(FocCurrentValidation_Push(&v,1750,1750)==0);
    assert(FocCurrentValidation_Push(&v,1410,1410)==0);
    assert(FocCurrentValidation_Push(&v,1800,1800)==0);
    assert(FocCurrentValidation_Push(&v,1300,1300)==-1);
    assert(v.current_unresolved_consecutive==3 && v.current_measurement_fault_count==1);
    assert(FocCurrentValidation_Push(&v,1560,1560)==-1);

    /* Real binding: raw safety / CUR_CONFIRM / driver fault remain independent. */
    safety_begin(); assert(push(900,1560)==0 && push(1560,1560)==1 && push(900,1560)==0);
    assert(!safety.protection.good_samples && safety.protection.confirm_cycles==2U);
    assert(push(1560,1560)==1 && push(1560,1560)==1);
    assert(safety.protection.cur_confirm_clear_count==1U && !safety.protection.pending);
    safety_begin(); assert(push(1200,1200)==0);
    for(unsigned i=1;i<CUR_CONFIRM_MAX_CYCLES;++i) assert(push(1200,1200)==1);
    assert(push(1200,1200)==-1 && safety.protection.reason==FOC_FP_TIMEOUT);
    assert(safety.protection.trip_mask==4U); /* reconstructed W, not selector */
    safety_begin(); assert(push(4096,1560)==-1 && safety.protection.reason==FOC_FP_RAW_INVALID);
    safety_begin();
    assert(FocFeedbackSafety_Push(&safety,1,50,1560,1560,0,FOC_FP_DRIVER_FAULT,1)==FOC_OC_TRIPPED);
    assert(safety.protection.reason==FOC_FP_HARDWARE);
    puts("PASS 100/40 inclusive boundaries, confirm=25, unresolved=3, raw safety and CUR_CONFIRM unchanged");
    return 0;
}
