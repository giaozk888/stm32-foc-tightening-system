#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "foc_current_protection_layers.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
/* Synthetic boundary and gain ONLY, not a recommended board configuration. */
static FocOcConfirmConfig cfg(float hard)
{ return (FocOcConfirmConfig){hard,1.0f/128.0f,2048,2048}; }
static void begin(FocCurrentProtection *s)
{ CHECK(FocProtection_Begin(s,FOC_PROTECT_OFFLINE_LAYERED,cfg(5),0)==FOC_OC_CLEAR); }
static void sample(FocCurrentProtection *s, unsigned n, unsigned hit)
{ FocProtection_Push(s,n,n*50U,hit?1535U:2048U,hit?2561U:2048U,1,0); }
int main(int argc, char **argv)
{
    CHECK(argc==2); unsigned test=(unsigned)strtoul(argv[1],NULL,10);
    FocCurrentProtection s;
    if (test==0) {
        begin(&s); sample(&s,0,1);
        CHECK(s.layer==FOC_PROTECT_MILD_CONFIRM && s.core.result==FOC_OC_PENDING);
        sample(&s,1,1);
        CHECK(s.layer==FOC_PROTECT_MILD_CONFIRM && s.core.reason==FOC_OC_TWO_OF_THREE);
        sample(&s,2,0); CHECK(s.core.result==FOC_OC_TRIPPED);
        FocProtection_Health(&s,FOC_PROTECT_HW_OVERCURRENT);
        CHECK(s.layer==FOC_PROTECT_MILD_CONFIRM && s.fault_flags==FOC_PROTECT_HW_OVERCURRENT);
        begin(&s); sample(&s,0,1); sample(&s,1,0); sample(&s,2,1);
        CHECK(s.layer==FOC_PROTECT_MILD_CONFIRM && s.core.result==FOC_OC_TRIPPED);
        begin(&s); sample(&s,0,1); sample(&s,1,0); sample(&s,2,0);
        CHECK(s.layer==FOC_PROTECT_NONE && s.core.singles==1);
    } else if (test==1) {
        for (unsigned sign=0;sign<2;++sign) {
            begin(&s);
            FocProtection_Push(&s,0,0,sign?2688:1408,sign?1408:2688,1,0);
            CHECK(s.layer==FOC_PROTECT_SEVERE_IMMEDIATE && s.core.trip_mask==3);
        }
        begin(&s); sample(&s,0,1);
        FocProtection_Push(&s,1,50,1664,1664,1,0); /* reconstructed W=6 A */
        CHECK(s.layer==FOC_PROTECT_SEVERE_IMMEDIATE && s.core.trip_mask==4);
        for (uint32_t flag=1;flag<=2;flag<<=1) {
            begin(&s); sample(&s,0,1); FocProtection_Poll(&s,25,flag);
            CHECK(s.layer==FOC_PROTECT_SEVERE_IMMEDIATE && s.core.result==FOC_OC_TRIPPED);
        }
    } else if (test==2) {
        for (uint32_t flag=4;flag<=64;flag<<=1) {
            begin(&s); sample(&s,0,1); FocProtection_Health(&s,flag);
            CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.core.result==FOC_OC_TRIPPED);
        }
        begin(&s); FocProtection_Push(&s,0,0,4096,2048,1,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.fault_flags==FOC_PROTECT_ADC_INVALID);
        begin(&s); FocProtection_Push(&s,0,0,2048,2048,0,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE);
        begin(&s); sample(&s,0,1);
        FocProtection_Push(&s,2,50,2048,2048,1,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.core.reason==FOC_OC_GAP);
        begin(&s); sample(&s,0,0); sample(&s,0,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.core.reason==FOC_OC_GAP);
    } else if (test==3) {
        begin(&s); CHECK(FocProtection_Poll(&s,100,0)==FOC_OC_CLEAR);
        FocProtection_Poll(&s,101,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.fault_flags==FOC_PROTECT_ADC_TIMEOUT);
        begin(&s); sample(&s,0,0); FocProtection_Poll(&s,101,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.fault_flags==FOC_PROTECT_ADC_TIMEOUT);
        begin(&s); FocProtection_Push(&s,0,101,2048,2048,1,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.fault_flags==FOC_PROTECT_ADC_TIMEOUT);
        begin(&s); sample(&s,0,1); FocProtection_Poll(&s,101,0);
        CHECK(s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.core.reason==FOC_OC_DEADLINE);
        FocProtection_Begin(&s,FOC_PROTECT_OFFLINE_LAYERED,cfg(5),UINT32_MAX-49U);
        FocProtection_Push(&s,UINT32_MAX,UINT32_MAX-49U,1535,2561,1,0);
        FocProtection_Push(&s,0,0,2048,2048,1,0);
        CHECK(s.core.result==FOC_OC_PENDING);
        FocProtection_Push(&s,1,50,2048,2048,1,0);
        CHECK(s.core.result==FOC_OC_CLEAR);
    } else if (test==4) {
        FocProtection_Begin(&s,FOC_PROTECT_STRICT_4A,cfg(4),0);
        FocProtection_Push(&s,0,0,1536,2560,1,0);
        CHECK(s.core.result==FOC_OC_CLEAR);
        sample(&s,1,1);
        CHECK(s.core.result==FOC_OC_TRIPPED && s.layer==FOC_PROTECT_SEVERE_IMMEDIATE);
        for (unsigned n=0;n<5;++n) {
            FocProtectionMode mode=n==0?FOC_PROTECT_STRICT_4A:n==4?(FocProtectionMode)99:FOC_PROTECT_OFFLINE_LAYERED;
            float hard=n==0?5:n==1?4:n==2?0:n==3?NAN:5;
            FocProtection_Begin(&s,mode,cfg(hard),0);
            CHECK(s.core.result==FOC_OC_TRIPPED && s.core.reason==FOC_OC_BAD_CONFIG &&
                  s.layer==FOC_PROTECT_SENSING_IMMEDIATE);
        }
        s=(FocCurrentProtection){0}; FocProtection_Poll(&s,0,0);
        CHECK(s.core.result==FOC_OC_TRIPPED && s.core.reason==FOC_OC_BAD_CONFIG);
    } else if (test==5) {
        begin(&s);
        for (unsigned n=0;n<9;++n) sample(&s,n,n%3==0);
        CHECK(s.core.reason==FOC_OC_REPEATED_SINGLES && s.layer==FOC_PROTECT_SENSING_IMMEDIATE);
        /* A healthy/repaired feedback value is not even an input to the API.
         * Subsequent healthy raw values also cannot clear the first fault. */
        sample(&s,9,0); CHECK(s.core.result==FOC_OC_TRIPPED);
    } else { CHECK(0); }
    puts("layered offline policy PASS; no power-control integration");
    return 0;
}
