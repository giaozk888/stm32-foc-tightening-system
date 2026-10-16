#include "pw_managed_buffer.h"
#include "pw_buffer_test_heap.h"
#include "uart_tx_pool.h"
#include <array>
#include <cassert>
#include <cstring>
#include <thread>
#include <cstdio>

void Empty() {
    PW_BufferDiagnostics stats{};
    PW_Buffer_GetDiagnostics(&stats);
    assert(stats.live_bytes == 0 && stats.live_objects == 0);
    assert(PW_BufferTest_LiveAllocations() == 0);
    for (auto bytes : stats.tag_bytes)
        assert(bytes == 0);
}
static void DmaRelease(uint32_t ref) {
    assert(PW_Buffer_Release(ref));
}
void HybridMpsc() {
    UartTxPool_Init();
    std::array<std::thread, 4> producers;
    for (unsigned id = 0; id < producers.size(); ++id) {
        producers[id] = std::thread([id] {
            for (unsigned sequence = 0; sequence < 1000; ++sequence) {
                PW_BufferLease payload{};
                while (!PW_Buffer_Allocate(513, PW_BUFFER_UART, &payload))
                    std::this_thread::yield();
                UartTxLease descriptor{};
                assert(UartTxPool_Acquire(1, &descriptor));
                const uint32_t header[] = {id, sequence, payload.token};
                std::memcpy(payload.data, header, sizeof(header));
                std::memset(payload.data + sizeof(header), (id + sequence) & 255U,
                            payload.capacity - sizeof(header));
                const uint8_t *data = payload.data;
                PW_BufferRef ref;
                assert(PW_Buffer_Seal(&payload, &ref));
                assert(UartTxPool_CommitReference(&descriptor, data, 513, DmaRelease, ref));
            }
        });
    }
    std::array<unsigned, 4> next{};
    for (unsigned done = 0; done < 4000;) {
        UartTxMessage dma{};
        if (!UartTxPool_Begin(&dma)) {
            std::this_thread::yield();
            continue;
        }
        uint32_t header[3];
        assert(dma.length == 513);
        std::memcpy(header, dma.data, sizeof(header));
        assert(header[0] < 4 && header[1] == next[header[0]]++);
        assert(PW_Buffer_View(header[2], nullptr) == dma.data);
        for (size_t i = sizeof(header); i < dma.length; ++i)
            assert(dma.data[i] == ((header[0] + header[1]) & 255U));
        // Simulated DMA completion: no producer can free before this callback.
        assert(UartTxPool_Finish(&dma));
        ++done;
    }
    for (auto &producer : producers)
        producer.join();
    assert(UartTxPool_ReservedBlocks() == 0 && UartTxPool_QueuedBytes() == 0);
    Empty();
}
int main() {
    PW_BufferLease lease{};
    assert(!PW_Buffer_Allocate(0, PW_BUFFER_TEMP, &lease));
    assert(!PW_Buffer_Allocate(2049, PW_BUFFER_TEMP, &lease));
    assert(!PW_Buffer_Allocate(1, PW_BUFFER_TAG_COUNT, &lease));
    for (auto context : {std::array<unsigned, 3>{1, 1, 1}, {0, 0, 1}, {0, 1, 4}}) {
        PW_BufferTest_SetContext(context[0], context[1], context[2]);
        assert(!PW_Buffer_Allocate(100, PW_BUFFER_TEMP, &lease));
    }
    PW_BufferTest_SetContext(0, 1, 1);
    PW_BufferTest_SetMasked(1);
    assert(!PW_Buffer_Allocate(100, PW_BUFFER_TEMP, &lease));
    PW_BufferTest_SetMasked(0);
    assert(PW_Buffer_Allocate(317, PW_BUFFER_UART, &lease));
    assert(lease.capacity == 317 && (reinterpret_cast<uintptr_t>(lease.data) & 7U) == 0);
    std::memset(lease.data, 0x74, lease.capacity);
    PW_BufferLease stale = lease;
    PW_BufferRef ref = 0;
    assert(PW_Buffer_Seal(&lease, &ref));
    assert(!lease.data && !PW_Buffer_Cancel(&stale) && !PW_Buffer_Seal(&stale, &ref));
    assert(PW_Buffer_Retain(ref));
    PW_BufferTest_SetContext(1, 1, 1);
    assert(!PW_Buffer_Release(ref));
    PW_BufferTest_SetContext(0, 1, 1);
    assert(PW_Buffer_Release(ref));
    size_t size = 0;
    assert(PW_Buffer_View(ref, &size)[316] == 0x74 && size == 317);
    assert(PW_Buffer_Release(ref));
    assert(!PW_Buffer_Release(ref) && !PW_Buffer_View(ref, nullptr));
    assert(PW_Buffer_Allocate(100, PW_BUFFER_TEMP, &lease));
    assert(!PW_Buffer_Cancel(&stale)); // reused slot, old generation forbidden
    assert(PW_Buffer_Cancel(&lease));
    Empty();

    std::array<PW_BufferLease, 17> slots{};
    for (size_t i = 0; i < 16; ++i)
        assert(PW_Buffer_Allocate(1, PW_BUFFER_TEMP, &slots[i]));
    assert(!PW_Buffer_Allocate(1, PW_BUFFER_TEMP, &slots[16]));
    for (size_t i = 0; i < 16; ++i)
        assert(PW_Buffer_Cancel(&slots[i]));
    assert(PW_Buffer_Allocate(2048, PW_BUFFER_TEMP, &slots[0]));
    assert(PW_Buffer_Allocate(2048, PW_BUFFER_UART, &slots[1]));
    assert(!PW_Buffer_Allocate(1, PW_BUFFER_TEMP, &slots[2]));
    assert(PW_Buffer_Cancel(&slots[0]) && PW_Buffer_Cancel(&slots[1]));
    PW_BufferTest_SetFreeHeap(PW_BUFFER_HEAP_RESERVE + 100);
    assert(!PW_Buffer_Allocate(100, PW_BUFFER_TEMP, &lease)); // header eats floor
    assert(PW_BufferTest_FreeHeap() == PW_BUFFER_HEAP_RESERVE + 100);
    PW_BufferTest_SetFreeHeap(40 * 1024);
    PW_BufferTest_FailAllocation(1);
    assert(!PW_Buffer_Allocate(100, PW_BUFFER_TEMP, &lease));
    PW_BufferTest_FailAllocation(0);
    Empty();

    std::array<std::thread, 4> threads;
    for (auto &thread : threads)
        thread = std::thread([] {
            for (unsigned i = 0; i < 3000; ++i) {
                PW_BufferLease scratch{};
                assert(PW_Buffer_Allocate(200 + i % 100, PW_BUFFER_TEMP, &scratch));
                scratch.data[scratch.capacity - 1] = 0xAA;
                assert(PW_Buffer_Cancel(&scratch));
            }
        });
    for (auto &thread : threads)
        thread.join();
    Empty();
    HybridMpsc();
    std::puts("PASS: real Pigweed backend, quotas, reserve/header, contexts, stale owners, shared "
              "refs, 12000 concurrent scratch objects + 4000 hybrid MPSC DMA-reference frames");
}
