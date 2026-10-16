#include <assert.h>
#include <stdio.h>
#include "foc_current_median.h"
int main(void)
{
    FocCurrentMedian m;
    uint16_t u = 99U, v = 98U;
    FocCurrentMedian_Begin(&m);
    assert(FocRunZeroMedian_Push(&m, 1560, 1561, 1560, 1561, 100, &u, &v) == 0);
    assert(FocRunZeroMedian_Push(&m, 1560, 1561, 1560, 1561, 100, &u, &v) == 0);
    assert(FocRunZeroMedian_Push(&m, 1560, 1561, 1560, 1561, 100, &u, &v) == 1);
    /* Median cannot turn a physically rejected raw spike into admission. */
    assert(FocRunZeroMedian_Push(&m, 1800, 1900, 1560, 1561, 100, &u, &v) == -1);
    assert(u == 1560 && v == 1561);
    assert(FocRunZeroMedian_Push(&m, 1560, 1561, 1560, 1561, 100, &u, &v) == 1);
    /* Sustained step appears in the median, not held indefinitely. */
    assert(FocRunZeroMedian_Push(&m, 1600, 1601, 1560, 1561, 100, &u, &v) == 1);
    assert(FocRunZeroMedian_Push(&m, 1600, 1601, 1560, 1561, 100, &u, &v) == 1);
    assert(u == 1600 && v == 1601);
    assert(FocRunZeroMedian_Push(&m, 5000, 1561, 1560, 1561, 100, &u, &v) == -1);
    assert(FocRunZeroMedian_Push(&m, 1560, 1561, 1560, 1561, -1, &u, &v) == -1);
    /* Exact boundaries remain allowed; one count beyond remains rejected. */
    FocCurrentMedian_Begin(&m);
    for (unsigned n = 0; n < 3; ++n)
        assert(FocRunZeroMedian_Push(&m, 1660, 1461, 1560, 1561, 100, &u, &v) == (n == 2 ? 1 : 0));
    assert(FocRunZeroMedian_Push(&m, 1661, 1461, 1560, 1561, 100, &u, &v) == -1);
    /* All scalar permutations, ties and full-scale values. */
    assert(FocMedian3_U16(0, 65535, 100) == 100);
    assert(FocMedian3_U16(100, 0, 65535) == 100);
    assert(FocMedian3_U16(65535, 100, 0) == 100);
    assert(FocMedian3_U16(100, 65535, 0) == 100);
    assert(FocMedian3_U16(65535, 0, 100) == 100);
    assert(FocMedian3_U16(0, 100, 65535) == 100);
    assert(FocMedian3_U16(100, 100, 65535) == 100);
    puts("RUN ZERO MEDIAN PASS: physical history, warmup, raw gate, boundary, sustained step, invalid raw.");
    return 0;
}
