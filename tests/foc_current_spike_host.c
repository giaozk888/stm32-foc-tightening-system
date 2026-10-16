#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#undef assert
/* No Windows CRT assertion dialog: offline CI failures exit immediately. */
#define assert(condition) do { if (!(condition)) { \
    fprintf(stderr, "CHECK failed line %d: %s\n", __LINE__, #condition); \
    exit(1); } } while (0)
#include "foc_current_median.h"
#include "foc_zero_median.h"

static FocCurrentMedian current_spike_filter;
static uint16_t current_med_u[3], current_med_v[3];
static uint8_t current_med_index, current_med_count, adc_fault;
static uint16_t iu_zero_raw = 1560, iv_zero_raw = 1560, iw_zero_raw = 1560;
static uint16_t iu_inj_raw, iv_inj_raw, iw_inj_raw;
static uint32_t current_valid_count, current_reject_count, current_reject_streak;
static int32_t current_last_rejected_sum_counts;
static uint32_t off_calls;
#define ADC_FULL_SCALE 4095U
#define CURRENT_REJECT_STREAK_LIMIT 20U
#define DRIVER_SD_GPIO_Port 0
#define DRIVER_SD_Pin 64U
#define GPIO_PIN_RESET 0
static void HAL_GPIO_WritePin(int port, unsigned pin, int value)
{ assert(!port && pin == 64 && !value); ++off_calls; }
static void runtime(uint16_t u, uint16_t v, uint8_t frame_ok,
                    int32_t step_u, int32_t step_v)
{
#include "foc_current_spike_runtime.inc"
}
static void reset(void)
{
    FocCurrentMedian_Begin(&current_spike_filter);
    iu_inj_raw = iv_inj_raw = iw_inj_raw = 1560;
    current_valid_count = current_reject_count = current_reject_streak = 0;
    adc_fault = 0; off_calls = 0;
}
static void sequence(const uint16_t *in, unsigned n, unsigned expected_spikes)
{
    FocCurrentMedian m; uint16_t u, v;
    unsigned spikes = 0, outputs = 0;
    FocCurrentMedian_Begin(&m);
    for (unsigned i = 0; i < n; ++i) {
        int ready = FocCurrentMedian_Push(&m, in[i], 1560, &u, &v);
        assert(ready == (i >= 2));
        if (!ready) continue;
        ++outputs;
        int isolated = FocSpike3_Isolated(in[i-2], in[i-1], in[i]);
        assert(m.last_spike_mask == isolated);
        assert(v == 1560);
        assert(u == (isolated ? (in[i-2]+in[i]+1U)/2U : in[i-1]));
        spikes += isolated;
    }
    assert(outputs == n-2 && spikes == expected_spikes);
}
int main(void)
{
    const uint16_t peak[] = {1500,1501,1900,1502,1503,1504};
    const uint16_t valley[] = {1500,1501,1100,1502,1503,1504};
    const uint16_t small[] = {1500,1510,1501,1504,1503};
    const uint16_t ramp[] = {1500,1550,1600,1650,1700,1750};
    const uint16_t step[] = {1500,1500,1900,1900,1900,1900};
    const uint16_t pulse[] = {1500,1500,1900,1900,1500,1500};
    sequence(peak,6,1); sequence(valley,6,1); sequence(small,5,0);
    sequence(ramp,6,0); sequence(step,6,0); sequence(pulse,6,0);
    assert(FocSpike3_Select(1500,1510,1501) == 1510);
    assert(!FocSpike3_Isolated(1500,1540,1500)); /* strictly above 40 */
    assert(FocSpike3_Isolated(1500,1541,1500));
    assert(FocSpike3_Isolated(1500,1551,1510)); /* endpoint boundary inclusive */
    assert(!FocSpike3_Isolated(1500,1700,1511));
    assert(!FocSpike3_Isolated(1500,1550,1510)); /* one side exactly 40 */
    assert(FocSpike3_Select(1563,1505,1562)==1563);
    assert(FocSpike3_Select(1562,1621,1563)==1563);
    assert(FocSpike3_Select(4094,3000,4095)==4095); /* sum/rounding */
    assert(!FocSpike3_Isolated(0,65535,0));
    assert(FocSpike3_Select(0,5000,0) == 5000);
    /* Raw startup admission remains independent of the isolated predicate. */
    FocCurrentMedian gate; uint16_t fu, fv;
    FocCurrentMedian_Begin(&gate);
    assert(FocRunZeroMedian_Push(&gate,1560,1560,1560,1560,100,&fu,&fv)==0);
    assert(FocRunZeroMedian_Push(&gate,1800,1560,1560,1560,100,&fu,&fv)==-1);
    assert(FocRunZeroMedian_Push(&gate,1560,1560,1560,1560,100,&fu,&fv)==1);
    assert(gate.last_spike_mask==1 && fu==1560);
    /* Execute the SAME locked-profile MCU include: interpolate marked U,
     * retain unmarked V at the same delayed center, preserve neighbors. */
    reset();
    runtime(1560,1560,1,0,0);
    runtime(1561,1561,1,1,1);
    runtime(1900,1562,0,339,1);
    assert(iu_inj_raw==1561 && iv_inj_raw==1561 && current_valid_count==1);
    runtime(1562,1563,0,-338,1);
    assert(current_spike_filter.last_spike_mask==1 && current_valid_count==2);
    assert(iu_inj_raw==1562 && iv_inj_raw==1562);
    runtime(1563,1564,1,1,1);
    assert(iu_inj_raw==1562 && iv_inj_raw==1563 && current_valid_count==3);
    assert(iw_inj_raw==1555 && !current_reject_streak);
    reset();
    for (unsigned n=0;n<20;++n) runtime(n%2?1900:1500,1560,0,400,0);
    assert(adc_fault && off_calls==1 && current_reject_streak==20);
    /* Known safety limitation, not an approval to use filtered-only trip:
     * a genuine one-cycle current pulse has exactly the same shape as EMI.
     * 840 counts is about 5.64 A at the project's 3.3 V/120 mV/A scale,
     * but this feedback branch holds zero current and only counts two edges.
     * An independent actual hardware/physical-sample protection is required.
     */
    reset();
    runtime(1560,1560,1,0,0); runtime(1560,1560,1,0,0);
    runtime(2400,1560,0,840,0); runtime(1560,1560,0,-840,0);
    assert(current_spike_filter.last_spike_mask == 1);
    assert(iu_inj_raw == 1560 && iv_inj_raw == 1560 && !adc_fault);
    assert(current_reject_streak == 2 && off_calls == 0);
    /* Normal/invalid/sustained faults are never disguised as zero success. */
    FocZeroMedian z; FocZeroCal cal;
    FocZeroMedian_Begin(&z,&cal,1560);
    for (unsigned n=0;n<24002;++n)
        FocZeroMedian_Push(&z,&cal,n==20100?1800:1560,1560);
    assert(cal.state==FOC_ZERO_READY && cal.zero_u==1560 && z.changed==1);
    assert(z.raw.state==FOC_ZERO_FAILED && z.outside_nominal==1);
    assert(z.pairs==24002 && z.raw_window_pairs==4002);
    FocZeroMedian_Begin(&z,&cal,1560);
    for (unsigned n=0;n<20002;++n) FocZeroMedian_Push(&z,&cal,1560,1560);
    for (unsigned n=0;n<3;++n) FocZeroMedian_Push(&z,&cal,1800,1560);
    assert(cal.state==FOC_ZERO_FAILED && z.changed==0);
    FocZeroMedian_Begin(&z,&cal,1560);
    FocZeroMedian_Push(&z,&cal,5000,1560);
    assert(cal.state==FOC_ZERO_FAILED && z.max_u==5000);
    puts("isolated-spike host PASS: dual thresholds, center interpolation, raw guards, chronological ring, calibration");
}
