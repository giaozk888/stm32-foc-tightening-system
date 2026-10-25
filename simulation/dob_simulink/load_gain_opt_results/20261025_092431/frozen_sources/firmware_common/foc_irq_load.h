#ifndef FOC_IRQ_LOAD_H
#define FOC_IRQ_LOAD_H
#include <stdint.h>
#if defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
#include "foc_irq_sources.h"
#endif
/* Union of measured ISR bodies: nested TIM7/encoder time counted once.
 * Caller serializes these core operations; unsigned deltas handle DWT wrap.
 * Does not cover exception stacking/unstacking or code outside the hooks. */
typedef struct { uint32_t total, start, depth; } FocIrqLoad;
static inline void FocIrqLoad_Begin(FocIrqLoad *s,uint32_t now)
{
    if (s->depth++==0U) s->start=now;
}
static inline void FocIrqLoad_End(FocIrqLoad *s,uint32_t now)
{
    if (s->depth && --s->depth==0U) s->total+=now-s->start;
}
static inline uint32_t FocIrqLoad_Total(const FocIrqLoad *s,uint32_t now)
{
    return s->total+(s->depth ? now-s->start : 0U);
}
#if defined(FOC_FAST_MATH)
void FocIrqLoad_Enter(void);
void FocIrqLoad_Leave(void);
uint32_t FocIrqLoad_Read(void);
#endif
#endif
