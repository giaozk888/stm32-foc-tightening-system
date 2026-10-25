#ifndef FOC_PWM_BOUNDARY_LITE_H
#define FOC_PWM_BOUNDARY_LITE_H
#include <stdint.h>
#include <limits.h>
#include "foc_hot_path.h"

/* Diagnostic only. Reuse the timing adapter's existing DWT and TIM1 reads;
 * retain two small records after the measured IRQ interval. This is a
 * software estimate, not active-CCR or analog-edge evidence. */
typedef struct {
    uint32_t seq, remaining, wall;
    uint8_t valid;
} FocPwmBoundaryLiteFrame;
typedef struct {
    FocPwmBoundaryLiteFrame first, worst;
} FocPwmBoundaryLite;

static FOC_RAM_PATH __attribute__((noinline)) void FocPwmBoundaryLite_Record(FocPwmBoundaryLite *s,
    uint32_t seq, uint32_t remaining, uint32_t wall, uint8_t entry_stable)
{
    if (!entry_stable || remaining > 8498U || wall > INT32_MAX || wall < remaining) return;
    FocPwmBoundaryLiteFrame frame = { seq, remaining, wall, 1U };
    if (!s->first.valid) s->first = frame;
    if (!s->worst.valid ||
        wall - remaining > s->worst.wall - s->worst.remaining)
        s->worst = frame;
}
#endif
