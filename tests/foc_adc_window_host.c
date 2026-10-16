#include "foc_adc_timing_stm32.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static unsigned plans;
static void verify(const FocWindowConfig *c, const FocWindowPlan *p)
{
    int t = p->trigger, end = t + c->latency_ticks + c->aperture_ticks;
    int period = 2 * c->arr, guard = c->dead_ticks + c->settle_ticks;
    assert(t > 0 && t < c->arr);
    assert(p->earliest <= t && t <= p->latest);
    for (unsigned i = 0; i < 3; ++i) {
        /* Independent exhaustive edge-distance oracle, including previous
         * and next periods; not the planner's interval construction. */
        for (int cycle = -1; cycle <= 1; ++cycle) {
            int edges[2] = {cycle * period + p->phase[i],
                            cycle * period + period - p->phase[i]};
            for (unsigned e = 0; e < 2; ++e)
                assert(end <= edges[e] - guard || t >= edges[e] + guard);
        }
    }
    if (c->topology == FOC_SENSE_LOW_SIDE_UV) {
        for (unsigned i = 0; i < 2; ++i) {
            assert(t >= p->phase[i] + guard);
            assert(t >= p->phase[i] + c->dead_ticks + c->min_low_on_ticks);
            assert(end <= period - p->phase[i] - guard);
        }
    }
    if (c->placement == FOC_SAMPLE_LATE_BEFORE_PEAK)
        assert(end < c->arr);
    ++plans;
}
/* Brute-force integer ticks; independent of interval choice and sorting.
 * RC placement must choose the globally latest safe tick, not the midpoint
 * of the widest segment or a time after the peak/update boundary. */
static int latest_oracle(const FocWindowConfig *c, const uint16_t phase[3])
{
    int period = 2 * c->arr;
    int guard = c->dead_ticks + c->settle_ticks;
    for (int t = c->arr - 1; t > 0; --t) {
        int end = t + c->latency_ticks + c->aperture_ticks;
        int valid = end < c->arr;
        for (unsigned i = 0; i < 3 && valid; ++i) {
            if (i < 2 && (t < phase[i] + guard ||
                t < phase[i] + c->dead_ticks + c->min_low_on_ticks ||
                end > period - phase[i] - guard)) valid = 0;
            for (int cycle = -1; cycle <= 1; ++cycle) {
                int edges[2] = {cycle * period + phase[i],
                                cycle * period + period - phase[i]};
                for (unsigned e = 0; e < 2; ++e)
                    if (!(end <= edges[e] - guard || t >= edges[e] + guard))
                        valid = 0;
            }
        }
        if (valid) return t;
    }
    return -1;
}
int main(void)
{
    FocWindowConfig c = {4249, 85, 85,
        FOC_ADC_TRIGGER_LATENCY_MAX_TICKS, 50, FOC_SENSE_LOW_SIDE_UV,
        0, FOC_SAMPLE_WINDOW_MIDPOINT};
    FocWindowPlan p;
    assert(FocAdcWindow_Duty(&c, .95f, .95f, .95f, &p) == FOC_WINDOW_OK);
    assert(p.phase[0] == 4037 && p.trigger == 4217 && p.slack_ticks == 20);
    printf("95%% reference: CCR=%u CH4=%u legal=[%u,%u] slack=%u ticks\n",
           p.phase[0], p.trigger, p.earliest, p.latest, p.slack_ticks);
    verify(&c, &p);
    uint16_t physical_95_ref[3] = {4080, 4080, 4080};
    assert(FocAdcWindow_Plan(&c, physical_95_ref, &p) == FOC_WINDOW_TOO_SHORT);
    c.settle_ticks = 170; /* 1us front-end recovery: same 95% is NOT feasible. */
    assert(FocAdcWindow_Duty(&c, .95f, .95f, .95f, &p) == FOC_WINDOW_TOO_SHORT);
    c.settle_ticks = 85;
    for (unsigned topo = 1; topo <= 2; ++topo) {
        c.topology = (FocSenseTopology)topo;
        for (unsigned u = 5; u <= 95; ++u)
            for (unsigned v = 5; v <= 95; ++v)
                for (unsigned w = 5; w <= 95; ++w) {
                    assert(FocAdcWindow_Duty(&c, u / 100.0f, v / 100.0f,
                                             w / 100.0f, &p) == FOC_WINDOW_OK);
                    verify(&c, &p);
                }
    }
    c.topology = FOC_SENSE_LOW_SIDE_UV;
    assert(FocAdcWindow_Duty(&c, -1, 2, .5f, &p) == FOC_WINDOW_OK);
    assert(p.phase[0] == 212 && p.phase[1] == 4037);
    verify(&c, &p);
    assert(FocAdcWindow_Duty(&c, NAN, .5f, .5f, &p) == FOC_WINDOW_BAD_ARGUMENT);
    assert(FocAdcWindow_Duty(&c, .5f, INFINITY, .5f, &p) == FOC_WINDOW_BAD_ARGUMENT);
    c.topology = FOC_SENSE_UNCONFIRMED;
    assert(FocAdcWindow_Duty(&c, .5f, .5f, .5f, &p) == FOC_WINDOW_TOPOLOGY_UNKNOWN);
    assert(FocAdcWindow_Duty(NULL, .5f, .5f, .5f, &p) == FOC_WINDOW_BAD_ARGUMENT);
    c.topology = FOC_SENSE_INLINE;
    uint16_t invalid[3] = {0, 100, 200};
    assert(FocAdcWindow_Plan(&c, invalid, &p) == FOC_WINDOW_BAD_ARGUMENT);
    c.aperture_ticks = 0;
    assert(FocAdcWindow_Duty(&c, .5f, .5f, .5f, &p) == FOC_WINDOW_BAD_ARGUMENT);

    c.aperture_ticks = 50;
    c.topology = FOC_SENSE_LOW_SIDE_UV;
    c.min_low_on_ticks = 1700; /* one nominal 10us RC, not fully settled */
    c.placement = FOC_SAMPLE_LATE_BEFORE_PEAK;
    assert(FocAdcWindow_Duty(&c, .5f, .5f, .5f, &p) == FOC_WINDOW_OK);
    assert(p.phase[0] == 2125 && p.earliest == 3910 &&
           p.trigger == 4184 && p.latest == 4184 && p.slack_ticks == 274);
    verify(&c, &p);
    printf("RC candidate 50%%: CCR=%u CH4=%u low-on=%u ticks; analog UNVERIFIED\n",
           p.phase[0], p.trigger, p.trigger - p.phase[0] - c.dead_ticks);
    assert(FocAdcWindow_Duty(&c, .55f, .5f, .45f, &p) == FOC_WINDOW_OK);
    verify(&c, &p);
    assert(FocAdcWindow_Duty(&c, .95f, .95f, .95f, &p) == FOC_WINDOW_TOO_SHORT);
    assert(p.trigger == 0); /* no stale plan on failure */
    c.min_low_on_ticks = 5100; /* three RC cannot fit: never silently relax */
    assert(FocAdcWindow_Duty(&c, .5f, .5f, .5f, &p) == FOC_WINDOW_TOO_SHORT);
    c.min_low_on_ticks = 1700;
    /* Exhaust safe geometry, including W edges splitting the low-side window. */
    unsigned rc_ok = 0, rc_rejected = 0;
    for (unsigned u = 5; u <= 95; ++u)
        for (unsigned v = 5; v <= 95; ++v)
            for (unsigned w = 5; w <= 95; ++w) {
                uint16_t phase[3] = {(uint16_t)(u * 4250U / 100U),
                    (uint16_t)(v * 4250U / 100U), (uint16_t)(w * 4250U / 100U)};
                FocWindowStatus st = FocAdcWindow_Plan(&c, phase, &p);
                assert(st == FOC_WINDOW_OK || st == FOC_WINDOW_TOO_SHORT);
                if (st == FOC_WINDOW_OK) { verify(&c, &p); ++rc_ok; }
                else { assert(p.trigger == 0); ++rc_rejected; }
                if (u % 10 == 5 && v % 10 == 5 && w % 10 == 5) {
                    int oracle = latest_oracle(&c, phase);
                    assert((st == FOC_WINDOW_OK) == (oracle >= 0));
                    if (oracle >= 0) assert(p.trigger == (unsigned)oracle);
                }
            }
    assert(rc_ok > 0 && rc_rejected > 0 && rc_ok + rc_rejected == 91U * 91U * 91U);
    printf("RC geometry: %u accepted, %u rejected; 1000 brute-force latest-tick comparisons\n",
           rc_ok, rc_rejected);
    c.topology = FOC_SENSE_INLINE;
    assert(FocAdcWindow_Duty(&c, .5f, .5f, .5f, &p) == FOC_WINDOW_BAD_ARGUMENT);
    c.topology = FOC_SENSE_LOW_SIDE_UV;
    c.placement = (FocSamplePlacement)99;
    assert(FocAdcWindow_Duty(&c, .5f, .5f, .5f, &p) == FOC_WINDOW_BAD_ARGUMENT);

    FocRawSpread s;
    FocRawSpread_Reset(&s);
    for (unsigned i = 0; i < 256; ++i) FocRawSpread_Push(&s, 4095, 2048);
    assert(s.sum_sq[0] == 4292870400U && s.sum[0] == 1048320U);
    assert(s.max_step[0] == 0 && s.min[1] == s.max[1]);
    FocRawSpread_Push(&s, 0, 0);
    assert(s.count == 256); /* Saturated block, no overflow. */
    FocRawSpread_Reset(&s);
    FocRawSpread_Push(&s, 100, 200);
    FocRawSpread_Push(&s, 104, 195);
    assert(s.max_step[0] == 4 && s.max_step[1] == 5);
    assert(s.sum[0] == 204 && s.sum_sq[0] == 20816);
    printf("PASS: %u independently checked plans; conservative invalid-window rejection; raw-spread bounds\n", plans);
    return 0;
}
