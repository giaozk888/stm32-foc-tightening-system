#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "foc_overcurrent_confirm.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
/* Exact 1/128 A/count permits exact boundary tests. 5 A is a SYNTHETIC
 * hard limit solely for exercising branches, not a proposed board setting. */
static FocOcConfirmConfig cfg(float hard)
{ return (FocOcConfirmConfig){hard,1.0f/128.0f,2048U,2048U}; }
static void feed(FocOcConfirm *s, unsigned n, uint8_t hit)
{
    /* u=4.0078125 A, v=-u -> W=0 when hit. */
    FocOcConfirm_Push(s,n,n*50U,hit?1535U:2048U,hit?2561U:2048U,1U);
}
static void patterns(void)
{
    /* Every six-sample binary pattern agrees with a simple 2-of-3 oracle.
     * Noise is also checked: third resolved single within 32 samples trips. */
    for (unsigned pattern=0;pattern<64U;++pattern) {
        FocOcConfirm s; FocOcConfirm_Begin(&s,cfg(5.0f));
        unsigned history=0U, pending=0U, misses=0U, singles=0U, trip=0U;
        for (unsigned n=0;n<6U;++n) {
            unsigned hit=(pattern>>n)&1U;
            history=((history<<1U)|hit)&7U;
            if (!trip) {
                if ((history&1U)+((history>>1U)&1U)+((history>>2U)&1U)>=2U) trip=1U;
                if (hit) { pending=1U; misses=0U; }
                else if (pending && ++misses>=2U) {
                    pending=0U; ++singles; if (singles>=3U) trip=1U;
                }
            }
            feed(&s,n,hit);
            CHECK((s.result==FOC_OC_TRIPPED)==(trip!=0U));
            if (!trip) CHECK((s.result==FOC_OC_PENDING)==(pending!=0U));
        }
    }
}
int main(void)
{
    FocOcConfirm s;
    CHECK(FocOcConfirm_Begin(&s,cfg(4.0f))==FOC_OC_CLEAR);
    FocOcConfirm_Push(&s,0,0,1536,2560,1); CHECK(s.result==FOC_OC_CLEAR); /* exactly 4 */
    feed(&s,1,1); CHECK(s.reason==FOC_OC_HARD); /* default first hit */
    feed(&s,2,0); CHECK(s.reason==FOC_OC_HARD); /* sticky */
    FocOcConfirm_Begin(&s,cfg(5)); feed(&s,0,1);
    CHECK(s.result==FOC_OC_PENDING);
    feed(&s,1,1); CHECK(s.reason==FOC_OC_TWO_OF_THREE && s.trip_mask==3);
    FocOcConfirm_Begin(&s,cfg(5)); feed(&s,0,1); feed(&s,1,0); feed(&s,2,1);
    CHECK(s.reason==FOC_OC_TWO_OF_THREE && s.last_us==100U);
    FocOcConfirm_Begin(&s,cfg(5)); feed(&s,0,1); feed(&s,1,0);
    CHECK(s.result==FOC_OC_PENDING); feed(&s,2,0);
    CHECK(s.result==FOC_OC_CLEAR && s.singles==1);
    FocOcConfirm_Begin(&s,cfg(5));
    FocOcConfirm_Push(&s,1,0,1408,2688,1); CHECK(s.reason==FOC_OC_HARD); /* exactly 5 */
    FocOcConfirm_Begin(&s,cfg(5));
    FocOcConfirm_Push(&s,1,0,2688,1408,1); CHECK(s.reason==FOC_OC_HARD && s.trip_mask==3);
    FocOcConfirm_Begin(&s,cfg(5));
    FocOcConfirm_Push(&s,1,0,2048,2561,1); CHECK(s.result==FOC_OC_PENDING);
    FocOcConfirm_Push(&s,2,50,1535,2048,1);
    CHECK(s.reason==FOC_OC_TWO_OF_THREE && s.trip_mask==7); /* different phases */
    FocOcConfirm_Begin(&s,cfg(5));
    FocOcConfirm_Push(&s,1,0,1664,1664,1); CHECK(s.reason==FOC_OC_HARD && s.trip_mask==4); /* W=6 */
    FocOcConfirm_Begin(&s,cfg(5)); feed(&s,0,1);
    CHECK(FocOcConfirm_CheckDeadline(&s,100)==FOC_OC_PENDING);
    CHECK(FocOcConfirm_CheckDeadline(&s,101)==FOC_OC_TRIPPED && s.reason==FOC_OC_DEADLINE);
    FocOcConfirm_Begin(&s,cfg(5)); feed(&s,0,1);
    FocOcConfirm_Push(&s,1,101,2048,2048,1); CHECK(s.reason==FOC_OC_DEADLINE);
    FocOcConfirm_Begin(&s,cfg(5)); feed(&s,0,1);
    FocOcConfirm_Push(&s,1,50,1408,2688,1); CHECK(s.reason==FOC_OC_HARD); /* pending cannot defer hard */
    FocOcConfirm_Begin(&s,cfg(5)); feed(&s,0,0);
    FocOcConfirm_Push(&s,1,101,2048,2048,1); CHECK(s.reason==FOC_OC_GAP);
    for (unsigned bad=0;bad<5U;++bad) {
        FocOcConfirm_Begin(&s,cfg(5)); feed(&s,1,1);
        FocOcConfirm_Push(&s,bad==0?3:bad==1?1:2,bad==2?50:100,
                         bad==3?4096:2048,2048,bad!=4);
        CHECK(s.result==FOC_OC_TRIPPED);
        CHECK(s.reason==(bad>=3?FOC_OC_BAD_SAMPLE:FOC_OC_GAP));
    }
    FocOcConfirm_Begin(&s,cfg(5));
    FocOcConfirm_Push(&s,UINT32_MAX,UINT32_MAX-49U,1535,2561,1);
    FocOcConfirm_Push(&s,0,0,1535,2561,1); CHECK(s.reason==FOC_OC_TWO_OF_THREE);
    for (unsigned bad=0;bad<6U;++bad) {
        FocOcConfirmConfig c=cfg(5);
        if (bad==0) c.hard_A=3;
        if (bad==1) c.hard_A=NAN;
        if (bad==2) c.hard_A=INFINITY;
        if (bad==3) c.count_to_A=0;
        if (bad==4) c.count_to_A=NAN;
        if (bad==5) c.zero_u=4096;
        CHECK(FocOcConfirm_Begin(&s,c)==FOC_OC_TRIPPED && s.reason==FOC_OC_BAD_CONFIG);
    }
    s=(FocOcConfirm){0}; feed(&s,0,0); CHECK(s.reason==FOC_OC_BAD_CONFIG);
    CHECK(FocOcConfirm_Finite(NAN)==0 && FocOcConfirm_Finite(INFINITY)==0 &&
          FocOcConfirm_Finite(-INFINITY)==0);
    FocOcConfirmConfig overflow=cfg(5); overflow.count_to_A=FLT_MAX;
    FocOcConfirm_Begin(&s,overflow);
    FocOcConfirm_Push(&s,0,0,0,0,1); CHECK(s.reason==FOC_OC_BAD_SAMPLE);
    FocOcConfirm_Begin(&s,cfg(5));
    for (unsigned n=0;n<9U;++n) feed(&s,n,n%3U==0U);
    CHECK(s.reason==FOC_OC_REPEATED_SINGLES && s.singles==3);
    FocOcConfirm_Begin(&s,cfg(5));
    for (unsigned n=0;n<81U;++n) feed(&s,n,n%39U==0U);
    CHECK(s.result!=FOC_OC_TRIPPED && s.singles==3); /* old singles expire */
    FocOcConfirm_Begin(&s,cfg(5)); s.singles=UINT32_MAX;
    feed(&s,0,1); feed(&s,1,0); feed(&s,2,0); CHECK(s.singles==UINT32_MAX);
    patterns();
    puts("offline bounded confirmation candidate PASS (NOT motor-qualified)");
    return 0;
}
