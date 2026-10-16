#include "foc_adc_window.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

FocWindowStatus FocAdcWindow_Reference(const FocWindowConfig *,
                                     const uint16_t[3], FocWindowPlan *);
static unsigned checks;
static void compare(const FocWindowConfig *c, const uint16_t phase[3])
{
    FocWindowPlan reference, actual;
    memset(&reference, 0xa5, sizeof reference);
    memset(&actual, 0x5a, sizeof actual);
    FocWindowStatus a = FocAdcWindow_Reference(c, phase, &reference);
    FocWindowStatus b = FocAdcWindow_Plan(c, phase, &actual);
    if (a != b || memcmp(&reference, &actual, sizeof actual)) {
        fprintf(stderr, "mismatch arr=%u phases=%u/%u/%u guard=%u+%u tail=%u+%u rc=%u topology=%d placement=%d\n",
                c->arr, phase[0], phase[1], phase[2], c->dead_ticks, c->settle_ticks,
                c->latency_ticks, c->aperture_ticks, c->min_low_on_ticks,
                (int)c->topology, (int)c->placement);
        assert(0);
    }
    ++checks;
}
static uint32_t seed = 0x16adc202U;
static uint32_t next(void)
{
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
}
int main(void)
{
    FocWindowConfig c = {4249,85,85,14,50,FOC_SENSE_LOW_SIDE_UV,
                         1700,FOC_SAMPLE_LATE_BEFORE_PEAK};
    for (unsigned u = 5; u <= 95; ++u)
        for (unsigned v = 5; v <= 95; ++v)
            for (unsigned w = 5; w <= 95; ++w) {
                uint16_t phase[3] = {(uint16_t)(u*4250U/100U),
                    (uint16_t)(v*4250U/100U), (uint16_t)(w*4250U/100U)};
                compare(&c, phase);
            }
    /* Exhaust small timers, edge orderings/ties, empty/one-tick windows,
     * zero and too-long guards, RC and latency budgets. */
    c.arr = 9;
    for (unsigned policy = 0; policy < 128; ++policy) {
        c.dead_ticks = policy & 1U;
        c.settle_ticks = (policy >> 1) & 3U;
        c.latency_ticks = (policy >> 3) & 1U;
        c.aperture_ticks = 1U + ((policy >> 4) & 1U);
        c.min_low_on_ticks = (policy >> 5) & 3U;
        for (unsigned u = 1; u < c.arr; ++u)
            for (unsigned v = 1; v < c.arr; ++v)
                for (unsigned w = 1; w < c.arr; ++w) {
                    uint16_t phase[3] = {(uint16_t)u,(uint16_t)v,(uint16_t)w};
                    compare(&c, phase);
                }
    }
    for (unsigned i = 0; i < 500000; ++i) {
        c.arr = (uint16_t)(4U + next()%32764U);
        c.dead_ticks = (uint16_t)(next()%80U);
        c.settle_ticks = (uint16_t)(next()%1000U);
        c.latency_ticks = (uint16_t)(next()%100U);
        c.aperture_ticks = (uint16_t)(1U + next()%200U);
        c.min_low_on_ticks = (uint16_t)(next()%32768U);
        c.topology = FOC_SENSE_LOW_SIDE_UV;
        c.placement = FOC_SAMPLE_LATE_BEFORE_PEAK;
        if (i%7U == 0) c.min_low_on_ticks = 0;
        if (i%11U == 0) c.topology = FOC_SENSE_INLINE;
        if (i%13U == 0) c.placement = FOC_SAMPLE_WINDOW_MIDPOINT;
        if (i%17U == 0) c.dead_ticks = UINT16_MAX;
        uint16_t phase[3] = {(uint16_t)(1U+next()%(c.arr-1U)),
            (uint16_t)(1U+next()%(c.arr-1U)), (uint16_t)(1U+next()%(c.arr-1U))};
        if (i%19U == 0) phase[0] = 0;
        if (i%23U == 0) c.arr = UINT16_MAX;
        if (i%29U == 0) c.aperture_ticks = 0;
        compare(&c, phase);
    }
    FocWindowPlan p;
    memset(&p, 0x5a, sizeof p);
    assert(FocAdcWindow_Duty(NULL,.5f,.5f,.5f,&p) == FOC_WINDOW_BAD_ARGUMENT);
    FocWindowPlan empty = {0};
    assert(!memcmp(&p, &empty, sizeof p));
    c = (FocWindowConfig){4249,85,85,14,50,FOC_SENSE_LOW_SIDE_UV,
                          1700,FOC_SAMPLE_LATE_BEFORE_PEAK};
    assert(FocAdcWindow_Duty(&c,NAN,.5f,.5f,&p) == FOC_WINDOW_BAD_ARGUMENT);
    assert(!memcmp(&p, &empty, sizeof p));
    assert(FocAdcWindow_Duty(&c,.5f,INFINITY,.5f,&p) == FOC_WINDOW_BAD_ARGUMENT);
    assert(!memcmp(&p, &empty, sizeof p));
    assert(FocAdcWindow_Duty(&c,.5f,.5f,.5f,NULL) == FOC_WINDOW_BAD_ARGUMENT);
    printf("PASS %u full-plan equivalence cases; no guard/budget changes\n", checks);
    return 0;
}
