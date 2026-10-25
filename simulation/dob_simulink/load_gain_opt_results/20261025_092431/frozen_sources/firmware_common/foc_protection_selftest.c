#include "foc_protection_selftest.h"
#include "foc_current_protection_layers.h"
#include <math.h>

static FocOcConfirmConfig Config(float hard)
{ return (FocOcConfirmConfig){hard, 1.0f/128.0f, 2048, 2048}; }
static void Begin(FocCurrentProtection *s)
{ (void)FocProtection_Begin(s, FOC_PROTECT_OFFLINE_LAYERED, Config(5), 0); }
static void Sample(FocCurrentProtection *s, uint32_t n, unsigned hit)
{ (void)FocProtection_Push(s,n,n*50U,hit?1535U:2048U,hit?2561U:2048U,1,0); }
#define CHECK(group, condition) do { ++r.checks; if (!(condition)) r.failures |= 1UL << (group); } while (0)

FocProtectionSelftestResult FocProtectionSelftest_Run(void)
{
    FocProtectionSelftestResult r={6,0,0};
    FocCurrentProtection s;
    /* 0: mild single, consecutive and spaced hits; first cause remains sticky. */
    Begin(&s); Sample(&s,0,1);
    CHECK(0,s.layer==FOC_PROTECT_MILD_CONFIRM && s.core.result==FOC_OC_PENDING);
    Sample(&s,1,1);
    CHECK(0,s.core.result==FOC_OC_TRIPPED && s.core.reason==FOC_OC_TWO_OF_THREE);
    Sample(&s,2,0); FocProtection_Health(&s,FOC_PROTECT_HW_OVERCURRENT);
    CHECK(0,s.layer==FOC_PROTECT_MILD_CONFIRM && s.core.result==FOC_OC_TRIPPED && s.fault_flags==1);
    Begin(&s); Sample(&s,0,1); Sample(&s,1,0); Sample(&s,2,1);
    CHECK(0,s.core.result==FOC_OC_TRIPPED && s.layer==FOC_PROTECT_MILD_CONFIRM);
    Begin(&s); Sample(&s,0,1); Sample(&s,1,0); Sample(&s,2,0);
    CHECK(0,s.core.result==FOC_OC_CLEAR && s.layer==FOC_PROTECT_NONE && s.core.singles==1);
    /* 1: exact synthetic severe boundary, both polarities, reconstructed W. */
    for (unsigned sign=0;sign<2;++sign) {
        Begin(&s); FocProtection_Push(&s,0,0,sign?2688:1408,sign?1408:2688,1,0);
        CHECK(1,s.layer==FOC_PROTECT_SEVERE_IMMEDIATE && s.core.result==FOC_OC_TRIPPED && s.core.trip_mask==3);
    }
    Begin(&s); Sample(&s,0,1); FocProtection_Push(&s,1,50,1664,1664,1,0);
    CHECK(1,s.layer==FOC_PROTECT_SEVERE_IMMEDIATE && s.core.trip_mask==4);
    for (uint32_t flag=1;flag<=2;flag<<=1) {
        Begin(&s); Sample(&s,0,1); FocProtection_Poll(&s,25,flag);
        CHECK(1,s.layer==FOC_PROTECT_SEVERE_IMMEDIATE && s.core.result==FOC_OC_TRIPPED);
    }
    /* 2: all sensing flags, unknown flag, invalid ADC, sequence loss/duplicate. */
    for (uint32_t flag=4;flag<=64;flag<<=1) {
        Begin(&s); Sample(&s,0,1); FocProtection_Health(&s,flag);
        CHECK(2,s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.core.result==FOC_OC_TRIPPED);
    }
    Begin(&s); FocProtection_Push(&s,0,0,4096,2048,1,0);
    CHECK(2,s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.fault_flags==FOC_PROTECT_ADC_INVALID);
    Begin(&s); FocProtection_Push(&s,0,0,2048,2048,0,0);
    CHECK(2,s.layer==FOC_PROTECT_SENSING_IMMEDIATE);
    Begin(&s); Sample(&s,0,1); FocProtection_Push(&s,2,50,2048,2048,1,0);
    CHECK(2,s.core.reason==FOC_OC_GAP);
    Begin(&s); Sample(&s,0,0); Sample(&s,0,0);
    CHECK(2,s.core.reason==FOC_OC_GAP);
    /* 3: no first sample, stalled normal stream, late arrival, pending deadline, wrap. */
    Begin(&s); CHECK(3,FocProtection_Poll(&s,100,0)==FOC_OC_CLEAR);
    FocProtection_Poll(&s,101,0);
    CHECK(3,s.layer==FOC_PROTECT_SENSING_IMMEDIATE && s.fault_flags==FOC_PROTECT_ADC_TIMEOUT);
    Begin(&s); Sample(&s,0,0); FocProtection_Poll(&s,101,0);
    CHECK(3,s.fault_flags==FOC_PROTECT_ADC_TIMEOUT);
    Begin(&s); FocProtection_Push(&s,0,101,2048,2048,1,0);
    CHECK(3,s.fault_flags==FOC_PROTECT_ADC_TIMEOUT);
    Begin(&s); Sample(&s,0,1); FocProtection_Poll(&s,101,0);
    CHECK(3,s.core.reason==FOC_OC_DEADLINE);
    FocProtection_Begin(&s,FOC_PROTECT_OFFLINE_LAYERED,Config(5),UINT32_MAX-49U);
    FocProtection_Push(&s,UINT32_MAX,UINT32_MAX-49U,1535,2561,1,0);
    FocProtection_Push(&s,0,0,2048,2048,1,0);
    CHECK(3,s.core.result==FOC_OC_PENDING);
    FocProtection_Push(&s,1,50,2048,2048,1,0);
    CHECK(3,s.core.result==FOC_OC_CLEAR);
    /* 4: unchanged strict 4 A, invalid/missing severe boundary fails closed. */
    FocProtection_Begin(&s,FOC_PROTECT_STRICT_4A,Config(4),0);
    FocProtection_Push(&s,0,0,1536,2560,1,0);
    CHECK(4,s.core.result==FOC_OC_CLEAR);
    Sample(&s,1,1);
    CHECK(4,s.core.result==FOC_OC_TRIPPED && s.layer==FOC_PROTECT_SEVERE_IMMEDIATE);
    for (unsigned n=0;n<5;++n) {
        FocProtectionMode mode=n==0?FOC_PROTECT_STRICT_4A:n==4?(FocProtectionMode)99:FOC_PROTECT_OFFLINE_LAYERED;
        float hard=n==0?5:n==1?4:n==2?0:n==3?NAN:5;
        FocProtection_Begin(&s,mode,Config(hard),0);
        CHECK(4,s.core.result==FOC_OC_TRIPPED && s.core.reason==FOC_OC_BAD_CONFIG);
    }
    s=(FocCurrentProtection){0}; FocProtection_Poll(&s,0,0);
    CHECK(4,s.core.reason==FOC_OC_BAD_CONFIG);
    /* 5: repeatedly resolving singles is a sensing fault, never auto-restart. */
    Begin(&s); for (unsigned n=0;n<9;++n) Sample(&s,n,n%3==0);
    CHECK(5,s.core.reason==FOC_OC_REPEATED_SINGLES && s.layer==FOC_PROTECT_SENSING_IMMEDIATE);
    Sample(&s,9,0); CHECK(5,s.core.result==FOC_OC_TRIPPED);
    return r;
}
