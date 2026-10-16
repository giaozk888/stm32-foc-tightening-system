/* Actual SPSC implementation, not a substitute model. No board access. */
#include "foc_adc_raw_buffer.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#if defined(_WIN32)
#include <windows.h>
#endif

static void block(FocRawBuffer *q, uint16_t u, uint16_t v, uint32_t plan)
{
    for (unsigned i = 0; i < FOC_SPREAD_BLOCK; ++i)
        FocRawBuffer_Push(q, u, v, 1000, 2000, 3000, 4000, plan);
}

static void contracts(void)
{
    FocRawBuffer q;
    FocRawBuffer_Init(&q);
    FocRawBlockView a, b;
    FocRawBufferInfo info;
    for (unsigned i = 0; i < 255; ++i)
        FocRawBuffer_Push(&q, 4095, 2048, 1000, 2000, 3000, 4000, 12);
    assert(!FocRawBuffer_Acquire(&q, &a));
    FocRawBuffer_Push(&q, 4095, 2048, 1000, 2000, 3000, 4000, 12);
    assert(FocRawBuffer_Acquire(&q, &a));
    assert(a.block->sequence == 1 && a.block->plan_sequence == 12 && !a.block->mixed);
    assert(a.block->sample[0][0] == 4095 && a.block->sample[255][1] == 2048);
    FocRawBlock frozen = *a.block;
    block(&q, 123, 456, 13);
    assert(FocRawBuffer_Acquire(&q, &b) && b.slot != a.slot);
    assert(b.block->sequence == 2 && b.block->sample[255][0] == 123);
    assert(!FocRawBuffer_Acquire(&q, &(FocRawBlockView){0}));
    block(&q, 999, 998, 14); /* Both READING: third block dropped. */
    assert(memcmp(a.block, &frozen, sizeof(frozen)) == 0);
    FocRawBuffer_Info(&q, &info);
    assert(info.reading == 2 && info.dropped_blocks == 1 && info.dropped_samples == 256);
    for (unsigned i = 0; i < 128; ++i)
        FocRawBuffer_Push(&q, 999, 998, 1000, 2000, 3000, 4000, 14);
    FocRawBuffer_Release(&q, &a); /* Available halfway through a dropped block. */
    for (unsigned i = 0; i < 128; ++i)
        FocRawBuffer_Push(&q, 999, 998, 1000, 2000, 3000, 4000, 14);
    assert(!FocRawBuffer_Acquire(&q, &a)); /* Must not send a discontinuous half block. */
    FocRawBuffer_Info(&q, &info);
    assert(info.dropped_blocks == 2 && info.dropped_samples == 512);
    FocRawBuffer_Release(&q, &b);
    block(&q, 777, 888, 15);
    assert(FocRawBuffer_Acquire(&q, &a));
    assert(a.block->sequence == 5 && a.block->sample[0][0] == 777);
    FocRawBuffer_Release(&q, &a);
    assert(!FocRawBuffer_Acquire(&q, &a));

    FocRawBuffer_Init(&q);
    FocRawBuffer_Push(&q, 65535, 1, 1, 2, 3, 4, 0);
    FocRawBuffer_Info(&q, &info);
    assert(info.rejected_samples == 1 && q.count == 0);
    for (unsigned i = 0; i < 128; ++i)
        FocRawBuffer_Push(&q, 1, 2, 1000, 2000, 3000, 4000, 3);
    for (unsigned i = 0; i < 128; ++i)
        FocRawBuffer_Push(&q, 1, 2, 1001, 2000, 3000, 4000, 4);
    assert(FocRawBuffer_Acquire(&q, &a));
    assert(a.block->mixed && a.block->command_phase[0] == 1000 && a.block->plan_sequence == 3);
    FocRawBuffer_Release(&q, &a);

    FocRawBuffer_Init(&q);
    q.next_sequence = UINT32_MAX - 1U;
    block(&q, 1, 2, 1); block(&q, 3, 4, 2);
    assert(FocRawBuffer_Acquire(&q, &a) && a.block->sequence == UINT32_MAX);
    FocRawBuffer_Release(&q, &a);
    block(&q, 5, 6, 3); /* Slot 0 reused; older wrapped sequence 0 still in slot 1. */
    assert(FocRawBuffer_Acquire(&q, &a) && a.block->sequence == 0);
    FocRawBuffer_Release(&q, &a);
    assert(FocRawBuffer_Acquire(&q, &a) && a.block->sequence == 1);
    FocRawBuffer_Release(&q, &a);
    puts("PASS: partial/ownership/backpressure/whole-block-drop/recovery/MIX/reject/rollover");
}

#if defined(_WIN32)
#define STRESS_BLOCKS 20000U
static FocRawBuffer stress_q;
static atomic_uint producer_done;
static uint32_t consumed, last_sequence;
static DWORD WINAPI producer(void *unused)
{
    (void)unused;
    for (uint32_t seq = 1; seq <= STRESS_BLOCKS; ++seq) {
        for (uint32_t i = 0; i < FOC_SPREAD_BLOCK; ++i) {
            uint16_t u = (uint16_t)((seq * 37U + i) & 4095U);
            FocRawBuffer_Push(&stress_q, u, u ^ 1023U, 1000, 2000, 3000, 4000, seq);
        }
        if ((seq & 31U) == 0U) SwitchToThread();
    }
    atomic_store_explicit(&producer_done, 1U, memory_order_release);
    return 0;
}
static DWORD WINAPI consumer(void *unused)
{
    (void)unused;
    for (;;) {
        FocRawBlockView view;
        if (!FocRawBuffer_Acquire(&stress_q, &view)) {
            if (atomic_load_explicit(&producer_done, memory_order_acquire)) {
                /* Recheck after acquiring done; the first queue probe could
                 * have preceded the producer's final READY publication. */
                if (!FocRawBuffer_Acquire(&stress_q, &view)) break;
            } else { SwitchToThread(); continue; }
        }
        const FocRawBlock *b = view.block;
        assert(b->sequence > last_sequence && b->sequence == b->plan_sequence && !b->mixed);
        for (unsigned i = 0; i < FOC_SPREAD_BLOCK; ++i) {
            uint16_t u = (uint16_t)((b->sequence * 37U + i) & 4095U);
            assert(b->sample[i][0] == u && b->sample[i][1] == (u ^ 1023U));
            if (i == 127U && (b->sequence & 7U) == 0U) SwitchToThread();
        }
        last_sequence = b->sequence; ++consumed;
        FocRawBuffer_Release(&stress_q, &view);
    }
    return 0;
}
static void stress(void)
{
    FocRawBuffer_Init(&stress_q);
    atomic_init(&producer_done, 0U);
    HANDLE handles[2] = {CreateThread(NULL, 0, consumer, NULL, 0, NULL),
                         CreateThread(NULL, 0, producer, NULL, 0, NULL)};
    assert(handles[0] && handles[1]);
    assert(WaitForMultipleObjects(2, handles, TRUE, 15000) == WAIT_OBJECT_0);
    CloseHandle(handles[0]); CloseHandle(handles[1]);
    FocRawBufferInfo info;
    FocRawBuffer_Info(&stress_q, &info);
    assert(consumed > 0 && consumed + info.dropped_blocks == STRESS_BLOCKS);
    assert(info.dropped_samples == info.dropped_blocks * FOC_SPREAD_BLOCK);
    assert(info.ready == 0 && info.reading == 0 && !info.rejected_samples);
    printf("PASS: two real host threads, %u sample pairs; processed=%lu dropped=%lu, no torn/reused/out-of-order block\n",
           STRESS_BLOCKS * FOC_SPREAD_BLOCK, (unsigned long)consumed, (unsigned long)info.dropped_blocks);
}
#endif
int main(void)
{
    contracts();
#if defined(_WIN32)
    stress();
#endif
    return 0;
}
