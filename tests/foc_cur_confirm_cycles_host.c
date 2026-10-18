/* Offline confirmation state-machine tests; never opens a device. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "foc_filtered_protection_candidate.h"

static FocFilteredProtection s;
static uint32_t seq, now;
static void begin(uint32_t t)
{
    seq=0U; now=t;
    assert(FocFp_Begin(&s,(FocFilteredProtectionConfig){4.0f,100U,100U,6U,4U},t)==FOC_OC_CLEAR);
}
static FocOcConfirmResult sample(unsigned suspicious, uint32_t dt)
{
    now+=dt;
    return FocFp_PushRawSafety(&s,++seq,now,suspicious?1400U:1563U,
        1560U,1563U,1560U,100U,0U);
}
static void entry(void)
{
    assert(sample(1U,50U)==FOC_OC_PENDING);
    assert(s.pending && !s.confirm_cycles && !s.good_samples);
    assert(s.cur_confirm_enter_count==1U);
}
int main(void)
{
    assert(CUR_CONFIRM_CLEAR_GOOD_SAMPLES==2U && CUR_CONFIRM_MAX_CYCLES==4U);
    begin(0U); entry();
    assert(sample(0U,50U)==FOC_OC_PENDING && s.good_samples==1U && s.confirm_cycles==1U);
    assert(sample(0U,53U)==FOC_OC_CLEAR); /* Board failure boundary: 103 us. */
    assert(!s.pending && !s.good_samples && !s.confirm_cycles && !s.pending_mask);
    assert(s.cur_confirm_max_cycles==2U && s.cur_confirm_max_elapsed_us==103U);
    assert(s.cur_confirm_clear_count==1U && !s.cur_confirm_fault_count);
    assert(sample(0U,50U)==FOC_OC_CLEAR && s.cur_confirm_enter_count==1U);
    assert(sample(1U,50U)==FOC_OC_PENDING && s.cur_confirm_enter_count==2U);

    begin(0U); entry();
    assert(sample(0U,50U)==FOC_OC_PENDING && s.good_samples==1U);
    assert(sample(1U,50U)==FOC_OC_PENDING && !s.good_samples && s.confirm_cycles==2U);
    assert(sample(0U,50U)==FOC_OC_PENDING);
    assert(sample(0U,50U)==FOC_OC_CLEAR); /* Final-cycle clear wins. */
    assert(s.cur_confirm_max_cycles==4U && s.cur_confirm_max_elapsed_us==200U);

    begin(0U); entry();
    for (unsigned i=1U;i<4U;++i) assert(sample(i&1U,50U)==FOC_OC_PENDING);
    assert(sample(1U,50U)==FOC_OC_TRIPPED);
    assert(s.reason==FOC_FP_TIMEOUT && s.timeout.reason==FOC_TO_CURRENT_CONFIRM);
    assert(!s.timeout.limit_us && s.confirm_cycles==4U && s.cur_confirm_fault_count==1U);
    assert(s.cur_confirm_max_cycles==4U && !s.cur_confirm_clear_count);
    assert(sample(0U,50U)==FOC_OC_TRIPPED && s.cur_confirm_fault_count==1U);

    begin(0U); entry();
    for (unsigned i=0U;i<3U;++i) assert(sample(1U,80U)==FOC_OC_PENDING);
    assert(s.cur_confirm_max_elapsed_us==240U); /* Not a 100/200 us wall timer. */
    assert(sample(1U,80U)==FOC_OC_TRIPPED && s.cur_confirm_max_elapsed_us==320U);

    begin(0U); entry();
    for (unsigned i=0U;i<3U;++i) assert(sample(1U,50U)==FOC_OC_PENDING);
    assert(sample(0U,50U)==FOC_OC_TRIPPED); /* Only ONE good on cycle four. */
    assert(s.good_samples==1U && !s.cur_confirm_clear_count && s.cur_confirm_fault_count==1U);

    begin(0U); s.cfg.confirm_deadline_us=1U; entry();
    assert(sample(0U,50U)==FOC_OC_PENDING && sample(0U,53U)==FOC_OC_CLEAR);
    assert(FocFp_Begin(&s,(FocFilteredProtectionConfig){4.0f,100U,0U,6U,4U},0U)==FOC_OC_CLEAR);
    assert(!s.cur_confirm_enter_count && !s.cur_confirm_max_elapsed_us);

    begin(UINT32_MAX-75U); entry();
    assert(sample(0U,50U)==FOC_OC_PENDING && sample(0U,53U)==FOC_OC_CLEAR);
    assert(s.cur_confirm_max_elapsed_us==103U && !s.cur_confirm_fault_count);

    begin(0U); entry();
    for (unsigned i=0U;i<10U;++i) assert(FocFp_Poll(&s,now+99U,0U)==FOC_OC_PENDING);
    assert(!s.confirm_cycles && !s.good_samples); /* Polls cannot spend ADC cycles. */
    assert(FocFp_Poll(&s,now+101U,0U)==FOC_OC_TRIPPED);
    assert(s.timeout.reason==FOC_TO_CURRENT_SAMPLE && !s.cur_confirm_fault_count);
    begin(0U); assert(FocFp_Poll(&s,101U,0U)==FOC_OC_TRIPPED);
    assert(s.timeout.reason==FOC_TO_CURRENT_FIRST_SAMPLE);

    for (unsigned phase=0U;phase<=4U;++phase) {
        begin(0U);
        if (phase) { entry(); for (unsigned i=1U;i<phase;++i) assert(sample(1U,50U)==FOC_OC_PENDING); }
        assert(FocFp_PushRawSafety(&s,seq+1U,now+50U,1400U,1560U,1563U,1560U,100U,
            FOC_FP_HW_TRIP)==FOC_OC_TRIPPED);
        assert(s.reason==FOC_FP_HARDWARE && !s.cur_confirm_fault_count && !s.timeout.reason);
    }
    begin(0U); entry();
    assert(FocFp_Poll(&s,now+101U,FOC_FP_DRIVER_FAULT)==FOC_OC_TRIPPED);
    assert(s.reason==FOC_FP_HARDWARE && !s.timeout.reason); /* Higher priority than timeout. */
    begin(0U); entry();
    assert(FocFp_PushRawSafety(&s,seq,now+50U,1563U,1560U,1563U,1560U,100U,0U)==FOC_OC_TRIPPED);
    assert(s.reason==FOC_FP_SEQUENCE && !s.confirm_cycles);
    begin(0U); entry(); ++seq;
    assert(sample(0U,50U)==FOC_OC_TRIPPED && s.reason==FOC_FP_SEQUENCE && !s.confirm_cycles);
    begin(0U); entry();
    assert(FocFp_PushRawSafety(&s,seq+1U,now+50U,4096U,1560U,1563U,1560U,100U,0U)==FOC_OC_TRIPPED);
    assert(s.reason==FOC_FP_RAW_INVALID && !s.confirm_cycles);

    begin(0U); s.cur_confirm_enter_count=s.cur_confirm_clear_count=UINT32_MAX;
    assert(sample(1U,50U)==FOC_OC_PENDING && s.cur_confirm_enter_count==UINT32_MAX);
    assert(sample(0U,50U)==FOC_OC_PENDING && sample(0U,50U)==FOC_OC_CLEAR);
    assert(s.cur_confirm_clear_count==UINT32_MAX);
    begin(0U); s.cur_confirm_fault_count=UINT32_MAX; entry();
    for (unsigned i=1U;i<4U;++i) assert(sample(1U,50U)==FOC_OC_PENDING);
    assert(sample(1U,50U)==FOC_OC_TRIPPED && s.cur_confirm_fault_count==UINT32_MAX);
    puts("PASS CUR_CONFIRM cycles, boundary, wrap, ADC watchdog and independent hardware trip");
    return 0;
}
