#ifndef FOC_ENCODER_TIMEOUT_DIAG_H
#define FOC_ENCODER_TIMEOUT_DIAG_H
#include "foc_timeout_diag.h"
#include "as5047p_dma_engine.h"
/* Called ONLY after Consume returned -1, with exactly the same timestamp.
 * Non-time errors (parity/EF/IO/zero interval) must not become timeouts. */
static inline FocTimeoutReason FocEncoder_TimeoutReason(
    const AsDmaCursor *c,const AsDmaSample *s,uint32_t now)
{
    if (s->status!=AS_DMA_OK) {
        if (s->status==AS_DMA_TIMEOUT) return FOC_TO_ENCODER_TRANSACTION;
        if (s->status==AS_DMA_CONTROL_STALE) return FOC_TO_ENCODER_CONTROL;
        if (s->status==AS_DMA_SCHEDULE) return FOC_TO_ENCODER_SCHEDULE;
        return FOC_TO_NONE;
    }
    if (now-s->sample_us>AS_DMA_SAMPLE_MAX_AGE_US) return FOC_TO_ENCODER_SAMPLE;
    if (s->elapsed_us>=AS_DMA_TRANSACTION_US) return FOC_TO_ENCODER_TRANSACTION;
    if (c->valid && s->sample_us-c->sample_us>AS_DMA_CONTROL_WATCHDOG_US)
        return FOC_TO_ENCODER_INTERVAL;
    return FOC_TO_NONE;
}
#endif
