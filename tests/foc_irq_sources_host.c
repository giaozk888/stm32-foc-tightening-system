#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "foc_irq_sources.h"

int main(void)
{
    FocIrqSources s={0}; FocIrqSourceFrame f;
    FocIrqSources_Enter(&s,FOC_IRQ_TX,0U);
    FocIrqSources_Leave(&s,FOC_IRQ_TX,10U);
    FocIrqSources_FrameBegin(&s);
    FocIrqSources_Enter(&s,FOC_IRQ_TIMER,100U);
    FocIrqSources_Enter(&s,FOC_IRQ_GUARD,110U);
    FocIrqSources_Leave(&s,FOC_IRQ_GUARD,130U);
    FocIrqSources_Leave(&s,FOC_IRQ_TIMER,140U);
    FocIrqSources_Enter(&s,FOC_IRQ_RX,150U);
    FocIrqSources_Leave(&s,FOC_IRQ_RX,157U);
    FocIrqSources_FrameEnd(&s,&f);
    assert(!f.error && f.cycles[0]==20U && f.cycles[1]==20U &&
           f.cycles[2]==7U && !f.cycles[3]);
    assert(s.stats.max_inclusive[1]==40U && s.stats.cycles[3]==10U);
    for (unsigned i=0U;i<3U;++i) assert(f.calls[i]==1U);
    FocIrqSources_FrameBegin(&s); FocIrqSources_FrameEnd(&s,&f);
    for (unsigned i=0U;i<4U;++i) assert(!f.cycles[i] && !f.calls[i]);
    FocIrqSources_FrameBegin(&s);
    FocIrqSources_Enter(&s,FOC_IRQ_GUARD,UINT32_MAX-4U);
    FocIrqSources_Leave(&s,FOC_IRQ_GUARD,5U);
    FocIrqSources_FrameEnd(&s,&f); assert(f.cycles[0]==10U);
    FocIrqSources_FrameBegin(&s); FocIrqSources_FrameEnd(&s,0);
    assert(!s.active && !s.stats.error);
    /* Valid arbitrary nesting, including equal IDs; compare an independent
     * segment model and total IRQ union, with unsigned clock wrap. */
    uint32_t rng=0x12345678U,now=UINT32_MAX-100U,expected[4]={0},union_sum=0U;
    unsigned stack[4],depth=0U;
    s=(FocIrqSources){0}; FocIrqSources_FrameBegin(&s);
    for (unsigned n=0U;n<1000000U;++n) {
        rng=rng*1664525U+1013904223U;
        uint32_t delta=(rng>>16U)&31U;
        if (depth) { expected[stack[depth-1U]]+=delta; union_sum+=delta; }
        now+=delta;
        if (!depth || (depth<4U && (rng&1U))) {
            unsigned id=(rng>>8U)&3U; stack[depth++]=id;
            FocIrqSources_Enter(&s,id,now);
        } else FocIrqSources_Leave(&s,stack[--depth],now);
    }
    while (depth) FocIrqSources_Leave(&s,stack[--depth],now);
    FocIrqSources_FrameEnd(&s,&f); uint32_t sum=0U;
    for (unsigned i=0U;i<4U;++i) {
        assert(f.cycles[i]==expected[i] && s.stats.cycles[i]==expected[i]); sum+=f.cycles[i];
    }
    assert(sum==union_sum && !f.error);
    s=(FocIrqSources){0}; FocIrqSources_Leave(&s,0U,0U); assert(s.stats.error);
    s=(FocIrqSources){0}; FocIrqSources_Enter(&s,4U,0U); assert(!s.depth && s.stats.error);
    s=(FocIrqSources){0}; FocIrqSources_Enter(&s,0U,0U);
    FocIrqSources_Leave(&s,1U,1U); assert(s.depth==1U && s.stats.error);
    s=(FocIrqSources){0};
    for (unsigned i=0U;i<5U;++i) FocIrqSources_Enter(&s,0U,i);
    assert(s.depth==4U && s.stats.error);
    FocIrqSources_FrameBegin(&s); FocIrqSources_FrameEnd(&s,&f); assert(f.error);
    s=(FocIrqSources){0}; FocIrqSources_FrameEnd(&s,&f); assert(f.error);
    s=(FocIrqSources){0}; FocIrqSources_FrameBegin(&s); FocIrqSources_FrameBegin(&s);
    FocIrqSources_FrameEnd(&s,&f); assert(f.error);
    puts("PASS exclusive nesting, wrap, million events, invalid hooks and frame boundaries");
    return 0;
}
