/* Exact functional comparison, not a host-speed or MCU timing benchmark. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "foc_feedback_safety_candidate.h"
static uint32_t random_state=UINT32_C(0x8ab3781d), digest=2166136261U;
static uint32_t next(void)
{
    random_state^=random_state<<13U; random_state^=random_state>>17U;
    random_state^=random_state<<5U; return random_state;
}
static void hash(uint32_t x) { digest=(digest^x)*16777619U; }
static uint32_t float_bits(float f)
{ uint32_t bits; memcpy(&bits,&f,sizeof bits); return bits; }
static void count_check(uint32_t bits)
{
    uint8_t ref=0U;
    for(unsigned i=0;i<32U;++i) ref+=(uint8_t)((bits>>i)&1U);
    assert(FocFp_Popcount(bits)==ref); hash(ref);
}
int main(void)
{
    count_check(0U); count_check(UINT32_MAX);
    for(unsigned i=0;i<32U;++i) { count_check(1U<<i); count_check(~(1U<<i)); }
    FocCurrentMedian filter; FocCurrentMedian_Begin(&filter);
    for(unsigned n=0;n<1000000U;++n) {
        count_check(next());
        /* Include non-ADC-range values to preserve the invalid-input selector. */
        uint16_t u=(uint16_t)(next()&((n%17U==0U)?65535U:4095U));
        uint16_t v=(uint16_t)(next()&((n%19U==0U)?65535U:4095U));
        uint16_t got_u=0U,got_v=0U;
        int ready=FocCurrentMedian_Push(&filter,u,v,&got_u,&got_v);
        if(ready) {
            unsigned p=filter.index,a=(p+1U)%4U,b=(p+2U)%4U,c=(p+3U)%4U;
            uint8_t mask=FocTrend4_Isolated(filter.u[p],filter.u[a],filter.u[b],filter.u[c]) |
                (uint8_t)(FocTrend4_Isolated(filter.v[p],filter.v[a],filter.v[b],filter.v[c])<<1U);
            assert(filter.last_spike_mask==mask);
            assert(got_u==FocTrend4_Select(filter.u[p],filter.u[a],filter.u[b],filter.u[c]));
            assert(got_v==FocTrend4_Select(filter.v[p],filter.v[a],filter.v[b],filter.v[c]));
            hash(got_u); hash(got_v); hash(mask);
        }
    }
    for(unsigned run=0;run<4096U;++run) {
        FocFeedbackSafety s;
        FocFeedbackSafetyConfig cfg={{4.0f,100U,100U,6U,4U},1551U,1551U,3300.0f/(4095.0f*120.0f)};
        uint32_t now=UINT32_MAX-500U,seq=UINT32_MAX-10U;
        assert(FocFeedbackSafety_Begin(&s,cfg,now)==FOC_OC_CLEAR);
        for(unsigned n=0;n<64U;++n) {
            now+=50U; ++seq;
            uint16_t u=(uint16_t)(1551+(int)(next()%41U)-20);
            uint16_t v=(uint16_t)(1551+(int)(next()%41U)-20);
            if((next()&31U)==0U) u=(uint16_t)(next()&4095U);
            uint32_t flags=run%17U==0U && n==10U?4U:0U;
            if(run%23U==0U && n==15U) now+=101U;
            if(run%31U==0U && n==17U) ++seq;
            FocOcConfirmResult result=FocFeedbackSafety_Push(&s,seq,now,u,v,(float)n*0.01f,flags,1U);
            FocFeedbackFrame frame;
            int ready=FocFeedbackSafety_Take(&s,now,0U,1U,&frame);
            hash((uint32_t)result); hash((uint32_t)ready); hash(s.protection.reason);
            hash(s.protection.raw_pairs); hash(s.protection.feedback_pairs);
            hash(s.protection.repair_window); hash(s.protection.repair_streak);
            hash(s.protection.repaired_pairs); hash(s.protection.fault_flags);
            hash(s.protection.pending); hash(s.protection.misses);
            hash(frame.source_seq); hash(frame.source_us); hash(frame.u); hash(frame.v);
            hash(frame.repaired_mask); hash(float_bits(frame.iu_A)); hash(float_bits(frame.iv_A));
            hash(float_bits(frame.iw_A)); hash(float_bits(frame.measurement_angle));
            hash(float_bits(frame.actuation_angle));
        }
    }
    printf("PASS million selector/popcount cases + 262144 feedback pushes, digest=%08lx\n",(unsigned long)digest);
    return 0;
}
