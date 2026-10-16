#include "pw_log_store.h"
#include "uart_tx_pool.h"
#include <array>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

static std::atomic<unsigned> released;
static void ReleaseLog(uint32_t ref)
{
    assert(PwLogStore_Release(ref));
    ++released;
}
static void Contracts()
{
    PwLogStore_Init();
    std::array<PwLogLease, PW_LOG_STORE_CAPACITY> leases{};
    for (auto &lease : leases) assert(PwLogStore_Acquire(&lease));
    PwLogLease failed{};
    assert(!PwLogStore_Acquire(&failed));
    assert(PwLogStore_Used() == PW_LOG_STORE_CAPACITY);
    for (auto &lease : leases) assert(PwLogStore_Cancel(&lease));
    assert(!PwLogStore_Cancel(&leases[0]));
    assert(PwLogStore_Used() == 0);
    PwLogLease lease{};
    PwLogRef ref{};
    assert(PwLogStore_Acquire(&lease));
    auto stale = lease;
    assert(!PwLogStore_Retain(lease.ref)); // not readable while writing
    assert(PwLogStore_View(lease.ref) == nullptr);
    lease.record->length = PW_LOG_TEXT_BYTES;
    assert(!PwLogStore_Seal(&lease, &ref));
    std::strcpy(lease.record->text, "hello"); lease.record->length = 5;
    auto *address = lease.record;
    assert(PwLogStore_Seal(&lease, &ref));
    assert(!PwLogStore_Seal(&lease, &ref));
    assert(PwLogStore_View(ref) == address && PwLogStore_Retain(ref));
    assert(PwLogStore_Release(ref));
    assert(PwLogStore_View(ref) == address);
    assert(PwLogStore_Release(ref));
    assert(!PwLogStore_Release(ref) && !PwLogStore_Retain(ref));
    assert(PwLogStore_Acquire(&lease));
    assert(!PwLogStore_Cancel(&stale));
    assert(!PwLogStore_Retain(ref));
    assert(PwLogStore_Cancel(&lease));
    assert(PwLogStore_Used() == 0);
}
static void Stress()
{
    constexpr unsigned producers = 4, per_producer = 15000;
    PwLogStore_Init(); UartTxPool_Init(); released = 0;
    std::atomic<unsigned> done{0};
    std::vector<std::thread> threads;
    for (unsigned id = 0; id < producers; ++id) threads.emplace_back([&, id] {
        std::array<PwLogRef, 4> history{};
        for (unsigned seq = 0; seq < per_producer; ++seq) {
            PwLogLease lease{};
            while (!PwLogStore_Acquire(&lease)) std::this_thread::yield();
            int length = std::snprintf(lease.record->text, PW_LOG_TEXT_BYTES,
                                      "%u %u %u", id, seq, lease.ref);
            assert(length > 0 && unsigned(length) < PW_LOG_TEXT_BYTES);
            lease.record->sequence = seq; lease.record->tick = seq;
            lease.record->level = 2; lease.record->length = uint16_t(length);
            PwLogRef ref{};
            assert(PwLogStore_Seal(&lease, &ref));
            assert(PwLogStore_Retain(ref)); // history independently pins the record
            UartTxLease descriptor{};
            while (!UartTxPool_Acquire(1, &descriptor)) std::this_thread::yield();
            auto *view = PwLogStore_View(ref);
            assert(view);
            assert(UartTxPool_CommitReference(&descriptor,
                    reinterpret_cast<const uint8_t *>(view->text), view->length, ReleaseLog, ref));
            // After publication, use only the separately owned history reference.
            if (history[seq % history.size()]) assert(PwLogStore_Release(history[seq % history.size()]));
            history[seq % history.size()] = ref;
        }
        for (auto ref : history) assert(PwLogStore_Release(ref));
        ++done;
    });
    std::array<unsigned, producers> next{};
    unsigned received = 0;
    while (received < producers * per_producer) {
        UartTxMessage message{};
        if (!UartTxPool_Begin(&message)) { std::this_thread::yield(); continue; }
        unsigned id, seq, ref;
        assert(std::sscanf(reinterpret_cast<const char *>(message.data), "%u %u %u", &id, &seq, &ref) == 3);
        assert(id < producers && seq == next[id]++);
        auto *view = PwLogStore_View(ref);
        assert(view && reinterpret_cast<const uint8_t *>(view->text) == message.data);
        assert(view->length == message.length && view->sequence == seq);
        std::this_thread::yield(); // keep in-flight owner while producers overwrite history
        assert(UartTxPool_Finish(&message));
        ++received;
    }
    for (auto &thread : threads) thread.join();
    assert(done == producers && released == producers * per_producer);
    assert(PwLogStore_Used() == 0 && UartTxPool_ReservedBlocks() == 0);
    std::puts("PASS: 60000 shared records, 4 producers, FIFO, exact DMA pointer, history overwrite and release");
}
int main() { Contracts(); Stress(); }
