#ifndef FOC_PWM_BOUNDARY_H
#define FOC_PWM_BOUNDARY_H
#include <stdint.h>
#include <limits.h>
#include "foc_irq_sources.h"

/* CPU/timer observations, NOT active-shadow or analog evidence. One timer
 * tick equals one DWT cycle only after the adapter's clock proof. No heap,
 * formatting, history reset or protection decision here. */
typedef struct {
    uint32_t seq, entry_count, exit_count, remaining, wall, irq;
    int32_t margin;
    FocIrqSourceFrame sources;
    uint8_t entry_down, exit_down, geometry, stable, dwt, valid;
} FocPwmBoundaryFrame;
typedef struct {
    uint32_t frames, invalid, late;
    FocPwmBoundaryFrame first_late, worst;
} FocPwmBoundary;

static inline void FocPwmBoundary_Record(FocPwmBoundary *s, FocPwmBoundaryFrame *f)
{
    uint32_t sum = 0U, overflow = 0U;
    for (unsigned i=0U; i<FOC_IRQ_SOURCE_N; ++i) {
        uint32_t next=sum+f->sources.cycles[i];
        if (next<sum) overflow=1U;
        sum=next;
    }
    f->valid = (uint8_t)(f->geometry && f->stable && f->dwt &&
        !f->sources.error && !overflow && f->irq <= f->wall && sum == f->irq &&
        f->remaining <= 8498U && f->wall <= INT32_MAX);
    /* Saturate corrupt/very long observations instead of signed overflow. */
    f->margin = f->remaining > 8498U ? 0 : f->wall > INT32_MAX ? INT32_MIN :
        (int32_t)f->remaining - (int32_t)f->wall;
    ++s->frames;
    if (!f->valid) { ++s->invalid; return; }
    if (!s->worst.valid || f->margin < s->worst.margin) s->worst = *f;
    if (f->margin <= 0) {
        ++s->late;
        if (!s->first_late.valid) s->first_late = *f;
    }
}
#endif
