#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "foc_current_median.h"
#include "foc_zero_median.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
static FocCurrentMedian current_spike_filter;
static uint16_t current_med_u[3], current_med_v[3];
static uint8_t current_med_index, current_med_count, adc_fault;
static uint16_t iu_zero_raw=1560, iv_zero_raw=1560, iw_zero_raw=1560;
static uint16_t iu_inj_raw=1560, iv_inj_raw=1560, iw_inj_raw=1560;
static uint32_t current_valid_count, current_reject_count, current_reject_streak, off_calls;
static int32_t current_last_rejected_sum_counts;
#define ADC_FULL_SCALE 4095U
#define CURRENT_REJECT_STREAK_LIMIT 20U
#define DRIVER_SD_GPIO_Port 0
#define DRIVER_SD_Pin 64U
#define GPIO_PIN_RESET 0
static void HAL_GPIO_WritePin(int port, unsigned pin, int value)
{ CHECK(!port && pin==64U && !value); ++off_calls; }
static void runtime(uint16_t u,uint16_t v,uint8_t frame_ok,int32_t step_u,int32_t step_v)
{
#include "foc_current_spike_runtime.inc"
}
int main(void)
{
    CHECK(FOC_CURRENT_HISTORY_PAIRS==4U);
    FocCurrentMedian_Begin(&current_spike_filter);
    runtime(1560,1560,1,0,0); runtime(1561,1561,1,1,1);
    runtime(1900,1562,0,339,1);
    CHECK(current_valid_count==0U); /* No stale warmup PI input. */
    runtime(1562,1563,0,-338,1);
    CHECK(current_spike_filter.last_spike_mask==1U && current_valid_count==1U);
    CHECK(iu_inj_raw==1562 && iv_inj_raw==1562 && iw_inj_raw==1556);
    CHECK(current_med_index==0U && current_med_count==3U);
    CHECK(current_med_u[0]==1561 && current_med_u[1]==1900 && current_med_u[2]==1562);
    runtime(1563,1564,1,1,1);
    CHECK(iu_inj_raw==1562 && iv_inj_raw==1563 && !current_reject_streak);
    for(unsigned n=0;n<20;++n) runtime(n%2?1900:1500,1560,0,400,0);
    CHECK(adc_fault && off_calls==1U && current_reject_streak==20U);
    CHECK(FocTrend4_Select(1560,1560,2400,1560)==1560);
    CHECK(FocTrend4_RawTrip(2400,1560,1560,1560,3300.0f/(4095.0f*120.0f),4.0f));
    CHECK(!FocTrend4_RawTrip(1560,1560,1560,1560,.0067f,4.0f));
    CHECK(FocTrend4_RawTrip(2000,2000,1560,1560,.0067f,4.0f)); /* reconstructed W */
    CHECK(FocTrend4_RawTrip(5000,1560,1560,1560,.0067f,4.0f));
    CHECK(FocTrend4_RawTrip(1560,1560,1560,1560,0.0f,4.0f));
    CHECK(!FocTrend4_RawTrip(1000,2000,2000,2000,.004f,4.0f));
    CHECK(FocTrend4_RawTrip(999,2000,2000,2000,.004f,4.0f));
    CHECK(!FocTrend4_RawTrip(3000,2000,2000,2000,.004f,4.0f));
    CHECK(FocTrend4_RawTrip(3001,2000,2000,2000,.004f,4.0f));
    FocTrend4Angle angle={0};
    FocTrend4Angle_Push(&angle,1.0f); FocTrend4Angle_Push(&angle,1.5f);
    CHECK(angle.center==1.0f && angle.previous==1.5f);
    FocTrend4Angle_Push(&angle,2.0f);
    CHECK(angle.center==1.5f && angle.previous==2.0f);
    /* Exact runtime/zero filter agreement on each chronological center. */
    FocZeroMedian zero; FocZeroCal cal; FocCurrentMedian stream;
    FocZeroMedian_Begin(&zero,&cal,1560); FocCurrentMedian_Begin(&stream);
    uint16_t fu=0,fv=0;
    for(unsigned n=0;n<24003U;++n) {
        uint16_t u=n==20100U?1800U:1560U;
        int ready=FocCurrentMedian_Push(&stream,u,1560,&fu,&fv);
        FocZeroMedian_Push(&zero,&cal,u,1560);
        if(n<3U) CHECK(!ready && cal.settled==0U);
        else { CHECK(ready); CHECK(cal.last_u==fu && cal.last_v==fv); }
        if(n<24002U) CHECK(cal.state!=FOC_ZERO_READY);
    }
    CHECK(cal.state==FOC_ZERO_READY && cal.zero_u==1560 && zero.changed==1U);
    CHECK(zero.raw.state==FOC_ZERO_FAILED && zero.outside_nominal==1U);
    CHECK(zero.pairs==24003U && zero.raw_window_pairs==4003U);
    FocZeroMedian_Begin(&zero,&cal,1560);
    FocZeroMedian_Push(&zero,&cal,5000,1560);
    CHECK(cal.state==FOC_ZERO_FAILED);
    puts("trend4 runtime, angle, raw-trip, zero PASS");
    return 0;
}
