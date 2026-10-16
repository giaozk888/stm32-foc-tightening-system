#include "foc_current_zero.h"
#include <assert.h>
#include <stdio.h>

static void Settle(FocZeroCal *c)
{
    for (unsigned i = 0U; i < FOC_ZERO_SETTLE_PAIRS; ++i)
        FocZero_Push(c, 0U, 4095U); /* Ignored, but retained in raw diagnostics. */
    assert(c->state == FOC_ZERO_COLLECTING && c->count == 0U);
}
static void Stable(FocZeroCal *c, unsigned n)
{
    for (unsigned i = 0U; i < n; ++i)
        FocZero_Push(c, (uint16_t)(1558U + i % 5U), (uint16_t)(1563U + i % 5U));
}
int main(void)
{
    FocZeroCal c, snapshot;
    const uint16_t span_low = (uint16_t)(1560U - FOC_ZERO_MAX_SPAN / 2U);
    const uint16_t span_high = (uint16_t)(span_low + FOC_ZERO_MAX_SPAN + 1U);
    assert(FOC_ZERO_MAX_SPAN == 100U);
    FocZero_Begin(&c, 1560U);
    assert(c.state == FOC_ZERO_SETTLING && c.zero_u == 0U);
    Settle(&c);
    Stable(&c, FOC_ZERO_WINDOW_PAIRS - 1U);
    assert(c.state == FOC_ZERO_COLLECTING && c.zero_u == 0U);
    FocZero_Push(&c, 1562U, 1567U);
    assert(c.state == FOC_ZERO_READY && c.zero_u == 1560U && c.zero_v == 1565U);
    FocZero_Snapshot(&c, &snapshot);
    FocZero_Push(&c, 0U, 0U);
    assert(c.state == FOC_ZERO_READY && c.total == snapshot.total);

    /* A failed window cannot contribute stale sums to the eventual zero. */
    FocZero_Begin(&c, 1560U); Settle(&c); Stable(&c, 1000U);
    FocZero_Push(&c, span_low, 1565U);
    FocZero_Push(&c, span_high, 1565U);
    assert(c.count == 0U && c.span_restarts == 1U && c.zero_u == 0U);
    Stable(&c, FOC_ZERO_WINDOW_PAIRS);
    assert(c.state == FOC_ZERO_READY && c.zero_u == 1560U);

    /* Slow drift may have a small total span: check half-window means too. */
    FocZero_Begin(&c, 1560U); Settle(&c);
    for (unsigned i = 0U; i < FOC_ZERO_WINDOW_PAIRS; ++i)
        FocZero_Push(&c, i < 2000U ? 1550U : 1560U, 1560U);
    assert(c.state == FOC_ZERO_COLLECTING && c.drift_restarts == 1U);
    assert(c.zero_u == 0U);
    Stable(&c, FOC_ZERO_WINDOW_PAIRS);
    assert(c.state == FOC_ZERO_READY);

    for (unsigned channel = 0U; channel < 2U; ++channel) {
        FocZero_Begin(&c, 1560U); Settle(&c);
        for (unsigned i = 0U; i < FOC_ZERO_MAX_RESTARTS; ++i) {
            FocZero_Push(&c, channel == 0U ? span_low : 1560U,
                              channel == 1U ? span_low : 1560U);
            FocZero_Push(&c, channel == 0U ? span_high : 1560U,
                              channel == 1U ? span_high : 1560U);
        }
        assert(c.state == FOC_ZERO_FAILED && c.reason == FOC_ZERO_UNSTABLE);
        assert(c.zero_u == 0U && c.zero_v == 0U);
    }
    const uint16_t bad[] = {0U, 999U, 2201U, 4095U, 1853U, 1814U};
    for (unsigned i = 0U; i < sizeof(bad) / sizeof(bad[0]); ++i) {
        FocZero_Begin(&c, 1560U); Settle(&c);
        FocZero_Push(&c, bad[i], 1560U);
        assert(c.state == FOC_ZERO_FAILED && c.reason == FOC_ZERO_OUT_OF_RANGE);
        FocZero_Push(&c, 1560U, 1560U);
        assert(c.state == FOC_ZERO_FAILED && c.zero_u == 0U);
    }
    FocZero_Begin(&c, 0U);
    assert(c.state == FOC_ZERO_FAILED && c.reason == FOC_ZERO_BAD_CONFIG);
    FocZero_Begin(&c, 1560U); Settle(&c); Stable(&c, 12U);
    FocZero_Abort(&c, FOC_ZERO_TIMEOUT);
    assert(c.state == FOC_ZERO_FAILED && c.zero_u == 0U);
    FocZero_Begin(&c, 1560U); Settle(&c);
    for (unsigned i = 0U; i < FOC_ZERO_WINDOW_PAIRS; ++i)
        FocZero_Push(&c, i < 2000U ? 1555U : 1560U, 1560U);
    assert(c.state == FOC_ZERO_READY); /* Exact drift boundary accepted. */

    /* Span 100 is accepted, but still needs the whole stable-mean window. */
    for (unsigned channel = 0U; channel < 2U; ++channel) {
        FocZero_Begin(&c, 1560U); Settle(&c);
        for (unsigned i = 0U; i < FOC_ZERO_WINDOW_PAIRS; ++i) {
            uint16_t value = (uint16_t)(span_low + (i % 2U) * FOC_ZERO_MAX_SPAN);
            FocZero_Push(&c, channel == 0U ? value : 1560U,
                              channel == 1U ? value : 1560U);
            if (i + 1U < FOC_ZERO_WINDOW_PAIRS) assert(c.zero_u == 0U && c.zero_v == 0U);
        }
        assert(c.state == FOC_ZERO_READY && c.zero_u == 1560U && c.zero_v == 1560U);
        assert(!c.restarts && c.count == FOC_ZERO_WINDOW_PAIRS);
    }
    /* The previously rejected 21-count span can pass only a full window. */
    FocZero_Begin(&c, 1560U); Settle(&c);
    for (unsigned i = 0U; i < FOC_ZERO_WINDOW_PAIRS; ++i)
        FocZero_Push(&c, i % 2U ? 1571U : 1550U, 1560U);
    assert(c.state == FOC_ZERO_READY && c.zero_u == 1561U && !c.restarts);
    /* Widening span must not widen the +/-100 nominal or 5-count drift gates. */
    FocZero_Begin(&c, 1560U); Settle(&c);
    FocZero_Push(&c, 1661U, 1560U);
    assert(c.state == FOC_ZERO_FAILED && c.reason == FOC_ZERO_OUT_OF_RANGE);
    FocZero_Begin(&c, 1560U); Settle(&c);
    for (unsigned i = 0U; i < FOC_ZERO_WINDOW_PAIRS; ++i)
        FocZero_Push(&c, i < FOC_ZERO_WINDOW_PAIRS / 2U ? 1554U : 1560U, 1560U);
    assert(c.state == FOC_ZERO_COLLECTING && c.drift_restarts == 1U && !c.zero_u);
    printf("STABLE ZERO HOST PASS: settle, 4000 contiguous raw pairs, range, drift, restart, timeout and no partial publication.\n");
    return 0;
}
