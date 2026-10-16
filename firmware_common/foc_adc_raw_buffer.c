#include "foc_adc_raw_buffer.h"
#include "foc_hot_path.h"
#include <limits.h>

_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "Raw ISR requires always-lock-free atomics");
_Static_assert(UINT_MAX == UINT32_MAX, "Raw ISR atomics must be 32-bit");
_Static_assert(sizeof(FocRawBuffer) <= 2176, "Two raw blocks must stay bounded");

void FocRawBuffer_Init(FocRawBuffer *q)
{
    q->count = q->write_slot = q->next_sequence = 0U;
    q->discarding = 0U;
    atomic_init(&q->state[0], FOC_RAW_FREE);
    atomic_init(&q->state[1], FOC_RAW_FREE);
    atomic_init(&q->dropped_blocks, 0U);
    atomic_init(&q->dropped_samples, 0U);
    atomic_init(&q->rejected_samples, 0U);
    /* Samples need not be cleared: exactly 256 writes precede READY. */
}

/* One producer only: load+store increments avoid an ISR exclusive retry loop. */
FOC_RAM_PATH static void increment(atomic_uint *counter)
{
    atomic_store_explicit(counter, atomic_load_explicit(counter, memory_order_relaxed) + 1U,
                          memory_order_relaxed);
}

FOC_RAM_PATH void FocRawBuffer_Push(FocRawBuffer *q, uint16_t u, uint16_t v,
                     uint16_t cu, uint16_t cv, uint16_t cw, uint16_t c4,
                     uint32_t plan_sequence)
{
    if (u > 4095U || v > 4095U) {
        increment(&q->rejected_samples);
        return;
    }
    if (q->count == 0U) {
        unsigned first = atomic_load_explicit(&q->state[0], memory_order_acquire);
        unsigned second = atomic_load_explicit(&q->state[1], memory_order_acquire);
        if (first == FOC_RAW_FREE || second == FOC_RAW_FREE) {
            q->write_slot = first == FOC_RAW_FREE ? 0U : 1U;
            FocRawBlock *b = &q->slot[q->write_slot];
            atomic_store_explicit(&q->state[q->write_slot], FOC_RAW_FILLING, memory_order_relaxed);
            b->command_phase[0] = cu; b->command_phase[1] = cv; b->command_phase[2] = cw;
            b->command_trigger = c4;
            b->plan_sequence = plan_sequence;
            b->mixed = 0U;
            q->discarding = 0U;
        } else {
            /* Drop the whole next 256 valid samples, even if a slot becomes
             * free halfway through. No discontinuous partial block is sent. */
            q->discarding = 1U;
        }
    }
    if (q->discarding != 0U) {
        increment(&q->dropped_samples);
        if (++q->count == FOC_SPREAD_BLOCK) {
            q->count = 0U;
            ++q->next_sequence;
            increment(&q->dropped_blocks);
        }
        return;
    }
    FocRawBlock *b = &q->slot[q->write_slot];
    if (cu != b->command_phase[0] || cv != b->command_phase[1] ||
        cw != b->command_phase[2] || c4 != b->command_trigger)
        b->mixed = 1U;
    b->sample[q->count][0] = u;
    b->sample[q->count][1] = v;
    if (++q->count == FOC_SPREAD_BLOCK) {
        b->sequence = ++q->next_sequence;
        /* Publish metadata and all sample writes BEFORE the READY state. */
        atomic_store_explicit(&q->state[q->write_slot], FOC_RAW_READY, memory_order_release);
        q->count = 0U;
    }
}

int FocRawBuffer_Acquire(FocRawBuffer *q, FocRawBlockView *view)
{
    unsigned a = atomic_load_explicit(&q->state[0], memory_order_acquire);
    unsigned b = atomic_load_explicit(&q->state[1], memory_order_acquire);
    if (a != FOC_RAW_READY && b != FOC_RAW_READY) return 0;
    /* The producer can publish BOTH blocks between these two loads. If only
     * one load saw READY, re-read the other AFTER acquiring that publication.
     * A single producer's earlier publication then happens-before this read,
     * so an older READY block cannot be skipped due to a stale first load.
     * READY storage cannot change until this consumer releases it. */
    if (a != FOC_RAW_READY)
        a = atomic_load_explicit(&q->state[0], memory_order_acquire);
    else if (b != FOC_RAW_READY)
        b = atomic_load_explicit(&q->state[1], memory_order_acquire);
    unsigned slot = a == FOC_RAW_READY ? 0U : 1U;
    /* At most two outstanding blocks. Unsigned comparison handles sequence
     * rollover. The order is unambiguous within half the 32-bit sequence range. */
    if (a == FOC_RAW_READY && b == FOC_RAW_READY &&
        (uint32_t)(q->slot[0].sequence - q->slot[1].sequence) < 0x80000000U)
        slot = 1U;
    atomic_store_explicit(&q->state[slot], FOC_RAW_READING, memory_order_relaxed);
    view->slot = slot;
    view->block = &q->slot[slot];
    return 1;
}

void FocRawBuffer_Release(FocRawBuffer *q, const FocRawBlockView *view)
{
    /* Consumer has finished all reads before the producer may reuse storage. */
    atomic_store_explicit(&q->state[view->slot], FOC_RAW_FREE, memory_order_release);
}

void FocRawBuffer_Info(const FocRawBuffer *q, FocRawBufferInfo *out)
{
    out->dropped_blocks = atomic_load_explicit(&q->dropped_blocks, memory_order_relaxed);
    out->dropped_samples = atomic_load_explicit(&q->dropped_samples, memory_order_relaxed);
    out->rejected_samples = atomic_load_explicit(&q->rejected_samples, memory_order_relaxed);
    unsigned a = atomic_load_explicit(&q->state[0], memory_order_acquire);
    unsigned b = atomic_load_explicit(&q->state[1], memory_order_acquire);
    out->ready = (unsigned)(a == FOC_RAW_READY) + (unsigned)(b == FOC_RAW_READY);
    out->reading = (unsigned)(a == FOC_RAW_READING) + (unsigned)(b == FOC_RAW_READING);
}
