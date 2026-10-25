#ifndef AS5047P_DMA_PUBLICATION_H
#define AS5047P_DMA_PUBLICATION_H
#include "as5047p_dma_engine.h"
/* Single serialized writer; any number of readers. Never spin while a lower
 * priority writer is suspended. A preempting FOC reads the previous complete
 * bank. Task readers reject an interrupted copy (bounded two attempts).
 * Port supplies a compiler + CPU barrier; no interrupt masking is required. */
#ifndef AS_DMA_PUBLICATION_BARRIER
#define AS_DMA_PUBLICATION_BARRIER() __DMB()
#endif
typedef struct {
    volatile AsDmaSample bank[2];
    volatile uint32_t generation;
} AsDmaPublication;
static inline void AsDma_Publish(AsDmaPublication *p,const AsDmaSample *s)
{
    uint32_t next=p->generation+1U;
    p->bank[next&1U]=*s;
    AS_DMA_PUBLICATION_BARRIER();
    p->generation=next; /* atomic aligned commit; includes failure publications */
}
static inline int AsDma_ReadPublished(const AsDmaPublication *p,AsDmaSample *s)
{
    for (unsigned attempt=0U;attempt<2U;++attempt) {
        uint32_t before=p->generation;
        AS_DMA_PUBLICATION_BARRIER();
        AsDmaSample copy=p->bank[before&1U];
        AS_DMA_PUBLICATION_BARRIER();
        if (before==p->generation) { *s=copy; return 1; }
    }
    return 0; /* no torn sample, no stale timestamp refreshed, no unbounded wait */
}
#endif
