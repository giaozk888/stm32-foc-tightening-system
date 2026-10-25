#ifndef FOC_IRQ_SOURCES_H
#define FOC_IRQ_SOURCES_H
#include <stdint.h>
/* Exclusive BODY segments, not physical exception latency. Nested sources
 * pause the parent; inclusive per-call MAX is explicitly separate. All calls
 * serialized by the adapter's short PRIMASK sections. Unsigned DWT deltas wrap.
 * Diagnostics only: an invalid hook order invalidates evidence, not protection.
 */
enum { FOC_IRQ_GUARD, FOC_IRQ_TIMER, FOC_IRQ_RX, FOC_IRQ_TX, FOC_IRQ_SOURCE_N };
enum { FOC_IRQ_STACK_N=4 };
typedef struct {
    uint32_t cycles[FOC_IRQ_SOURCE_N], calls[FOC_IRQ_SOURCE_N], error;
} FocIrqSourceFrame;
typedef struct {
    uint32_t cycles[FOC_IRQ_SOURCE_N], calls[FOC_IRQ_SOURCE_N];
    uint32_t max_inclusive[FOC_IRQ_SOURCE_N], error;
} FocIrqSourceStats;
typedef struct {
    FocIrqSourceStats stats;
    FocIrqSourceFrame frame;
    uint32_t start[FOC_IRQ_STACK_N], segment;
    uint8_t source[FOC_IRQ_STACK_N], depth, active;
} FocIrqSources;

static inline void FocIrqSources_Error(FocIrqSources *s)
{ s->stats.error=1U; s->frame.error=1U; }
static inline void FocIrqSources_Charge(FocIrqSources *s,uint32_t now)
{
    if (s->depth && s->depth<=FOC_IRQ_STACK_N) {
        unsigned id=s->source[s->depth-1U];
        uint32_t delta=now-s->segment;
        s->stats.cycles[id]+=delta;
        if (s->active) s->frame.cycles[id]+=delta;
    }
    s->segment=now;
}
static inline void FocIrqSources_Enter(FocIrqSources *s,unsigned id,uint32_t now)
{
    if (id>=FOC_IRQ_SOURCE_N || s->depth>=FOC_IRQ_STACK_N) {
        FocIrqSources_Error(s); return;
    }
    FocIrqSources_Charge(s,now);
    s->source[s->depth]=(uint8_t)id; s->start[s->depth]=now; ++s->depth;
    ++s->stats.calls[id];
    if (s->active) ++s->frame.calls[id];
}
static inline void FocIrqSources_Leave(FocIrqSources *s,unsigned id,uint32_t now)
{
    if (!s->depth || id>=FOC_IRQ_SOURCE_N || s->source[s->depth-1U]!=id) {
        FocIrqSources_Error(s); return;
    }
    FocIrqSources_Charge(s,now);
    uint32_t inclusive=now-s->start[s->depth-1U];
    if (inclusive>s->stats.max_inclusive[id]) s->stats.max_inclusive[id]=inclusive;
    --s->depth;
}
static inline void FocIrqSources_FrameBegin(FocIrqSources *s)
{
    /* ADC is below all measured sources: no measured IRQ may be active here. */
    if (s->depth || s->active) FocIrqSources_Error(s);
    for (unsigned i=0U;i<FOC_IRQ_SOURCE_N;++i) {
        s->frame.cycles[i]=0U; s->frame.calls[i]=0U;
    }
    s->frame.error=s->stats.error; s->active=1U;
}
static inline void FocIrqSources_FrameEnd(FocIrqSources *s,FocIrqSourceFrame *out)
{
    if (s->depth || !s->active) FocIrqSources_Error(s);
    s->active=0U;
    if (out) {
        for (unsigned i=0U;i<FOC_IRQ_SOURCE_N;++i) {
            out->cycles[i]=s->frame.cycles[i]; out->calls[i]=s->frame.calls[i];
        }
        out->error=s->frame.error;
    }
}
#if defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
void FocIrqSource_Enter(unsigned id);
void FocIrqSource_Leave(unsigned id);
void FocIrqSource_FrameBegin(void);
void FocIrqSource_FrameEnd(FocIrqSourceFrame *out);
void FocIrqSource_Stats(FocIrqSourceStats *out);
#endif
#endif
