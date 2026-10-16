#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "foc_filtered_protection_candidate.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
/* All thresholds/times here are OFFLINE branch-test values, not motor settings. */
static FocFilteredProtectionConfig cfg(void)
{ return (FocFilteredProtectionConfig){4.0f,100U,100U,3U,2U}; }
static void begin(FocFilteredProtection *s)
{
    CHECK(FocFp_Begin(s,cfg(),0U)==FOC_OC_CLEAR);
    for (uint32_t n=0;n<3U;++n)
        CHECK(FocFp_Push(s,n,n*50U,1560U,1560U,0U,0U,0,0,0U,0U)==FOC_OC_CLEAR);
}
static FocOcConfirmResult sample(FocFilteredProtection *s, uint32_t n,
    uint16_t raw_u, uint16_t raw_v, float u, float v, uint8_t repair, uint32_t flags)
{ return FocFp_Push(s,n,n*50U,raw_u,raw_v,1U,n-1U,u,v,repair,flags); }
int main(int argc,char **argv)
{
    CHECK(argc==2); unsigned test=(unsigned)strtoul(argv[1],NULL,10);
    FocFilteredProtection s;
    if (test==0) {
        begin(&s);
        /* Valid full-scale raw values have no software amplitude trip. */
        CHECK(sample(&s,3,0,4095,0,0,3,0)==FOC_OC_CLEAR);
        CHECK(sample(&s,4,1560,1560,0,0,0,0)==FOC_OC_CLEAR);
        CHECK(s.repaired_pairs==1U && s.feedback_pairs==2U);
        CHECK(sample(&s,5,1560,1560,4,0,0,0)==FOC_OC_CLEAR);
        CHECK(sample(&s,6,1560,1560,4.01f,0,0,0)==FOC_OC_PENDING);
        CHECK(sample(&s,7,1560,1560,0,0,0,0)==FOC_OC_PENDING);
        CHECK(sample(&s,8,1560,1560,0,0,0,0)==FOC_OC_CLEAR);
        begin(&s);
        /* No hidden severe-amplitude limit: even this synthetic large value
         * follows confirmation. Only safe as an OFFLINE / HARD-OFF example. */
        CHECK(sample(&s,3,1560,1560,100,-100,0,0)==FOC_OC_PENDING);
        CHECK(sample(&s,4,1560,1560,100,-100,0,0)==FOC_OC_TRIPPED);
        CHECK(s.reason==FOC_FP_CONFIRMED_CURRENT);
    } else if (test==1) {
        for (unsigned gap=0;gap<2U;++gap) {
            begin(&s); CHECK(sample(&s,3,1560,1560,4.01f,0,0,0)==FOC_OC_PENDING);
            if (gap) CHECK(sample(&s,4,1560,1560,0,0,0,0)==FOC_OC_PENDING);
            CHECK(sample(&s,4+gap,1560,1560,0,-4.01f,0,0)==FOC_OC_TRIPPED);
            CHECK(s.reason==FOC_FP_CONFIRMED_CURRENT && s.trip_mask==7U);
            sample(&s,5+gap,1560,1560,0,0,0,0); CHECK(s.result==FOC_OC_TRIPPED);
            FocFp_Poll(&s,(5+gap)*50U,FOC_FP_HW_TRIP);
            CHECK(s.reason==FOC_FP_CONFIRMED_CURRENT && s.fault_flags==FOC_FP_HW_TRIP);
        }
        begin(&s); sample(&s,3,1560,1560,2.1f,2.1f,0,0);
        CHECK(s.result==FOC_OC_PENDING && s.pending_mask==4U);
    } else if (test==2) {
        for (uint32_t flag=1U;flag<=16U;flag<<=1U) {
            begin(&s); FocFp_Poll(&s,125U,flag);
            CHECK(s.result==FOC_OC_TRIPPED);
            CHECK(s.reason==(flag<=2U?FOC_FP_HARDWARE:FOC_FP_HEALTH));
        }
        begin(&s); sample(&s,3,4096U,1560,0,0,0,0);
        CHECK(s.reason==FOC_FP_RAW_INVALID);
        for (unsigned n=0;n<3U;++n) {
            begin(&s); sample(&s,3,1560,1560,n==0?NAN:n==1?INFINITY:FLT_MAX,FLT_MAX,0,0);
            CHECK(s.reason==FOC_FP_FEEDBACK_INVALID);
        }
        begin(&s); sample(&s,3,1560,1560,0,0,4U,0); CHECK(s.reason==FOC_FP_FEEDBACK_INVALID);
        begin(&s); FocFp_Push(&s,3,150,1560,1560,2,2,0,0,0,0);
        CHECK(s.reason==FOC_FP_FEEDBACK_INVALID);
        FocFp_Poll(&s,151,FOC_FP_HW_TRIP|FOC_FP_DRIVER_FAULT);
        CHECK(s.reason==FOC_FP_FEEDBACK_INVALID && s.fault_flags==3U);
    } else if (test==3) {
        FocFp_Begin(&s,cfg(),0); CHECK(FocFp_Poll(&s,100,0)==FOC_OC_CLEAR);
        CHECK(FocFp_Poll(&s,101,0)==FOC_OC_TRIPPED);
        begin(&s); sample(&s,3,1560,1560,0,0,0,0); FocFp_Poll(&s,251,0);
        CHECK(s.reason==FOC_FP_TIMEOUT);
        begin(&s); sample(&s,3,1560,1560,4.1f,0,0,0);
        sample(&s,4,1560,1560,0,0,0,0); FocFp_Poll(&s,251,0);
        CHECK(s.reason==FOC_FP_TIMEOUT);
        begin(&s); sample(&s,4,1560,1560,0,0,0,0); CHECK(s.reason==FOC_FP_SEQUENCE);
        begin(&s); sample(&s,3,1560,1560,0,0,0,0);
        FocFp_Push(&s,4,150,1560,1560,1,3,0,0,0,0); CHECK(s.reason==FOC_FP_SEQUENCE);
        begin(&s); sample(&s,3,1560,1560,0,0,0,0);
        FocFp_Push(&s,4,149,1560,1560,1,3,0,0,0,0); CHECK(s.reason==FOC_FP_TIMEOUT);
        begin(&s); sample(&s,3,1560,1560,0,0,0,0);
        FocFp_Push(&s,4,200,1560,1560,1,1,0,0,0,0); CHECK(s.reason==FOC_FP_FEEDBACK_INVALID);
        begin(&s); FocFp_Push(&s,3,150,1560,1560,0,0,0,0,0,0); CHECK(s.reason==FOC_FP_FEEDBACK_MISSING);
        begin(&s); sample(&s,3,1560,1560,0,0,0,0);
        FocFp_Push(&s,4,200,1560,1560,0,0,0,0,0,0); CHECK(s.reason==FOC_FP_FEEDBACK_MISSING);
        FocFp_Begin(&s,cfg(),UINT32_MAX-149U);
        for (uint32_t n=0;n<4U;++n)
            CHECK(FocFp_Push(&s,UINT32_MAX-2U+n,UINT32_MAX-149U+n*50U,
                1560,1560,n==3U,UINT32_MAX-3U+n,0,0,0,0)==FOC_OC_CLEAR);
    } else if (test==4) {
        begin(&s); for (uint32_t n=3;n<6;++n) sample(&s,n,1560,1560,0,0,1,0);
        CHECK(s.reason==FOC_FP_REPAIR_BUDGET && s.repaired_pairs==3U);
        begin(&s); for (uint32_t n=3;n<=9;++n) sample(&s,n,1560,1560,0,0,(uint8_t)(n%2U),0);
        CHECK(s.reason==FOC_FP_REPAIR_BUDGET && s.repaired_pairs==4U);
        begin(&s); sample(&s,3,1560,1560,0,0,1,0);
        for (uint32_t n=4;n<=35;++n) sample(&s,n,1560,1560,0,0,0,0);
        CHECK(s.repair_window==0 && s.result==FOC_OC_CLEAR);
        s.raw_pairs=s.feedback_pairs=s.repaired_pairs=UINT32_MAX;
        sample(&s,36,1560,1560,0,0,1,0);
        CHECK(s.raw_pairs==UINT32_MAX && s.feedback_pairs==UINT32_MAX && s.repaired_pairs==UINT32_MAX);
    } else if (test==5) {
        for (unsigned n=0;n<12U;++n) {
            FocFilteredProtectionConfig c=cfg();
            if (n==0) c.soft_A=NAN;
            if (n==1) c.soft_A=0;
            if (n==2) c.sample_deadline_us=0;
            if (n==3) c.confirm_deadline_us=0;
            if (n==4) c.repair_hits_per_32=0;
            if (n==5) c.repair_hits_per_32=33;
            if (n==6) c.repair_streak=0;
            if (n==7) c.soft_A=INFINITY;
            if (n==8) c.soft_A=-1;
            if (n==9) c.sample_deadline_us=UINT32_MAX;
            if (n==10) c.confirm_deadline_us=UINT32_MAX;
            if (n==11) c.repair_streak=33;
            FocFp_Begin(&s,c,0); CHECK(s.reason==FOC_FP_CONFIG);
        }
        s=(FocFilteredProtection){0}; FocFp_Poll(&s,0,0); CHECK(s.reason==FOC_FP_CONFIG);
    } else if (test==6) {
        /* Exhaustive six-pair filtered masks vs independent two-of-three oracle. */
        for (unsigned pattern=0;pattern<64U;++pattern) {
            begin(&s); unsigned history=0U; unsigned tripped=0U;
            for (unsigned n=0;n<6U;++n) {
                unsigned hit=(pattern>>n)&1U; history=((history<<1U)|hit)&7U;
                if ((history&1U)+((history>>1U)&1U)+((history>>2U)&1U)>=2U) tripped=1U;
                sample(&s,n+3U,1560,1560,hit?4.01f:0,0,0,0);
                CHECK((s.result==FOC_OC_TRIPPED)==tripped);
            }
        }
    } else if (test==7) {
        FocFilteredProtectionConfig c=cfg();
        c.repair_hits_per_32=6U; c.repair_streak=4U;
        CHECK(FocFp_Begin(&s,c,0U)==FOC_OC_CLEAR);
        for (uint32_t n=0;n<3U;++n)
            CHECK(FocFp_Push(&s,n,n*50U,1560,1560,0,0,0,0,0,0)==FOC_OC_CLEAR);
        for (uint32_t n=3;n<=13U;++n)
            CHECK(sample(&s,n,1560,1560,0,0,n%2U?3U:0U,0)==FOC_OC_CLEAR);
        /* A repaired U+V pair still counts ONE, not two. */
        CHECK(s.repaired_pairs==6U && FocFp_Popcount(s.repair_window)==6U);
        CHECK(sample(&s,14,1560,1560,0,0,0,0)==FOC_OC_CLEAR);
        CHECK(sample(&s,15,1560,1560,0,0,1,0)==FOC_OC_TRIPPED);
        CHECK(s.reason==FOC_FP_REPAIR_BUDGET && s.repaired_pairs==7U);
        CHECK(s.repair_streak==1U);
        CHECK(sample(&s,16,1560,1560,0,0,0,0)==FOC_OC_TRIPPED);
    } else if (test==8) {
        FocFilteredProtectionConfig c=cfg();
        c.repair_hits_per_32=6U; c.repair_streak=4U;
        FocFp_Begin(&s,c,0U);
        for (uint32_t n=0;n<3U;++n)
            FocFp_Push(&s,n,n*50U,1560,1560,0,0,0,0,0,0);
        for (uint32_t n=3;n<=6U;++n)
            CHECK(sample(&s,n,1560,1560,0,0,1,0)==FOC_OC_CLEAR);
        CHECK(s.repair_streak==4U && s.repaired_pairs==4U);
        CHECK(sample(&s,7,1560,1560,0,0,1,0)==FOC_OC_TRIPPED);
        CHECK(s.reason==FOC_FP_REPAIR_BUDGET && s.repair_streak==5U);
        CHECK(FocFp_Popcount(s.repair_window)==5U); /* Window budget not exceeded. */
        FocFp_Begin(&s,c,0U);
        for (uint32_t n=0;n<3U;++n)
            FocFp_Push(&s,n,n*50U,1560,1560,0,0,0,0,0,0);
        CHECK(sample(&s,3,1560,1560,0,0,1,0)==FOC_OC_CLEAR);
        for (uint32_t n=4;n<=35U;++n)
            CHECK(sample(&s,n,1560,1560,0,0,0,0)==FOC_OC_CLEAR);
        CHECK(s.repair_window==0U && s.repair_streak==0U);
        CHECK(sample(&s,36,1560,1560,4.01f,0,0,0)==FOC_OC_PENDING);
        CHECK(sample(&s,37,1560,1560,4.01f,0,0,0)==FOC_OC_TRIPPED);
        CHECK(s.reason==FOC_FP_CONFIRMED_CURRENT);
    } else CHECK(0);
    puts("filtered protection candidate PASS; no motor-power integration"); return 0;
}
