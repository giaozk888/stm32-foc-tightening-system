#include "as5047p_dma_engine.h"
#include "as5047p_protocol.h"
#include "foc_hot_path.h"
#include <string.h>
#if defined(FOC_IRQ_COMPACT) && !defined(AS_DMA_BIND)
#error Compact engine must be compiled inside its fixed STM32 port
#endif

/* The generic engine remains callable with arbitrary test/port ops. The
 * compact STM32 translation unit binds these SAME operations to its fixed
 * register callbacks; no state transition, timestamp or fault ordering changes. */
#ifndef AS_DMA_BIND
#define AS_DMA_BIND(name, e) ((e)->ops->name)
#define AS_DMA_HAS_FAULT_SNAPSHOT(e) ((e)->ops->fault_snapshot != 0)
#endif

FOC_RAM_PATH int AsDma_TimeReached(uint32_t now, uint32_t due)
{
    return (int32_t)(now - due) >= 0;
}

int AsDma_Consume(AsDmaCursor *c, const AsDmaSample *s, uint32_t now, uint32_t *dt)
{
    if (s->status == AS_DMA_PENDING) return 0;
    if (s->status != AS_DMA_OK || now - s->sample_us > AS_DMA_SAMPLE_MAX_AGE_US ||
        s->elapsed_us >= AS_DMA_TRANSACTION_US) return -1;
    if (c->valid && c->sequence == s->sequence) return 0;
    uint32_t interval = c->valid ? s->sample_us - c->sample_us : AS_DMA_PERIOD_US;
    if (!interval || interval > AS_DMA_CONTROL_WATCHDOG_US) return -1;
    c->sequence = s->sequence;
    c->sample_us = s->sample_us;
    c->valid = 1U;
    *dt = interval;
    return 1;
}

void AsDma_Init(AsDmaEngine *e, const AsDmaOps *ops, void *context)
{
    memset(e, 0, sizeof(*e));
    e->ops = ops;
    e->context = context;
    e->sample.status = AS_DMA_PENDING;
}

FOC_RAM_PATH static void Complete(AsDmaEngine *e, AsDmaStatus status, uint32_t now)
{
    if (status != AS_DMA_OK && status != AS_DMA_CANCELLED &&
        AS_DMA_HAS_FAULT_SNAPSHOT(e))
        AS_DMA_BIND(fault_snapshot, e)(e->context, e, status, now);
    AS_DMA_BIND(stop_word, e)(e->context);
    AS_DMA_BIND(cs, e)(e->context, 1);
    AS_DMA_BIND(deadline, e)(e->context, 0, 0);
    e->state = AS_DMA_IDLE;
    e->sample.status = status;
    e->sample.sample_us = e->word_rx_us;
    e->sample.completed_us = now;
    e->sample.elapsed_us = now - e->started_us;
    e->sample.response = e->response;
    e->sample.raw = status == AS_DMA_OK ? (e->response & 0x3FFFU) : 0U;
    e->sample.errfl = e->errfl;
    e->sample.errfl_valid = e->errfl_valid;
    e->sample.recovered = e->recovered;
    if (e->sample.elapsed_us > e->max_elapsed_us) e->max_elapsed_us = e->sample.elapsed_us;
    if (status == AS_DMA_OK) ++e->successes;
    else if (status != AS_DMA_CANCELLED) ++e->failures;
    ++e->sample.sequence; /* publish last; port makes snapshot atomic */
    AS_DMA_BIND(finish, e)(e->context, status);
}

FOC_RAM_PATH void AsDma_Fail(AsDmaEngine *e, AsDmaStatus status, uint32_t now)
{
    Complete(e, status, now);
}

FOC_RAM_PATH void AsDma_CheckDeadline(AsDmaEngine *e, uint32_t now)
{
    if (e->state != AS_DMA_IDLE && AsDma_TimeReached(now, e->deadline_us))
        Complete(e, AS_DMA_TIMEOUT, now);
}

FOC_RAM_PATH static void GuardAfter(AsDmaEngine *e, AsDmaState state, uint32_t now)
{
    e->state = state;
    e->guard_us = now + AS_DMA_GUARD_US;
    AS_DMA_BIND(guard, e)(e->context, e->guard_us);
}

FOC_RAM_PATH int AsDma_Begin(AsDmaEngine *e, uint16_t reg, uint32_t now)
{
    if (e->state != AS_DMA_IDLE) return 0;
    e->reg = reg & 0x3FFFU;
    e->frame = 0U;
    e->errfl = e->response = 0U;
    e->errfl_valid = e->recovered = 0U;
    e->started_us = now;
    e->word_rx_us = now;
    e->deadline_us = now + AS_DMA_TRANSACTION_US;
    e->tx = AS5047P_MakeReadCommand(e->reg);
    e->rx = 0U;
    ++e->attempts;
    AS_DMA_BIND(cs, e)(e->context, 0);
    GuardAfter(e, AS_DMA_SETUP, now);
    AS_DMA_BIND(deadline, e)(e->context, 1, e->deadline_us);
    return 1;
}

FOC_RAM_PATH void AsDma_RxComplete(AsDmaEngine *e, uint32_t now)
{
    AsDma_CheckDeadline(e, now);
    if (e->state != AS_DMA_WORD) return; /* late/spurious completion */
    e->word_rx_us = now;
    AS_DMA_BIND(stop_word, e)(e->context);
    GuardAfter(e, AS_DMA_BIND(busy, e)(e->context) ? AS_DMA_TAIL : AS_DMA_HOLD, now);
}

/* Called only after BSY clears and the post-clock CS-low guard elapsed. */
FOC_RAM_PATH static void FinishFrame(AsDmaEngine *e, uint32_t now)
{
    uint16_t value = e->rx;
    AS_DMA_BIND(cs, e)(e->context, 1);
    if ((e->frame & 1U) != 0U) {
        if (AS5047P_ParityIsOdd(value)) { Complete(e, AS_DMA_PARITY, now); return; }
        e->response = value;
        if (e->frame == 3U) {
            e->errfl = AS5047P_ErrorFlags(value);
            e->errfl_valid = 1U;
        } else if (!(value & 0x4000U) || e->reg != 0x3FFFU) {
            e->recovered = e->frame == 5U;
            Complete(e, AS_DMA_OK, now);
            return;
        } else if (e->frame == 5U) {
            Complete(e, AS_DMA_EF, now);
            return;
        }
    }
    ++e->frame;
    e->tx = AS5047P_MakeReadCommand((e->frame & 1U) ? 0U :
                                  (e->frame == 2U ? 1U : e->reg));
    GuardAfter(e, AS_DMA_GAP, now);
}

FOC_RAM_PATH void AsDma_Guard(AsDmaEngine *e, uint32_t now)
{
    AsDma_CheckDeadline(e, now);
    if (e->state == AS_DMA_IDLE || e->state == AS_DMA_WORD ||
        !AsDma_TimeReached(now, e->guard_us)) return;
    switch (e->state) {
    case AS_DMA_SETUP:
        e->state = AS_DMA_WORD;
        if (!AS_DMA_BIND(start_word, e)(e->context, &e->tx, &e->rx)) Complete(e, AS_DMA_IO, now);
        break;
    case AS_DMA_TAIL:
        GuardAfter(e, AS_DMA_BIND(busy, e)(e->context) ? AS_DMA_TAIL : AS_DMA_HOLD, now);
        break;
    case AS_DMA_HOLD:
        FinishFrame(e, now);
        break;
    case AS_DMA_GAP:
        AS_DMA_BIND(cs, e)(e->context, 0);
        GuardAfter(e, AS_DMA_SETUP, now);
        break;
    default: break;
    }
}
