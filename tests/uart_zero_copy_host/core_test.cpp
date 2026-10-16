#include "uart_tx_pool.h"
#include "uart_rx_cursor.h"
#include "uart_line_parser.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstring>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

static void PoolContracts()
{
    UartTxPool_Init();
    UartTxLease lease{};
    UartTxMessage message{};
    assert(!UartTxPool_Acquire(0, &lease));
    assert(!UartTxPool_Acquire(UART_TX_POOL_BYTES + 1, &lease));
    assert(!UartTxPool_Begin(&message));
    assert(UartTxPool_Acquire(UART_TX_POOL_BYTES, &lease));
    const auto *address = lease.data;
    const auto stale = lease;
    std::memset(lease.data, 0x5a, lease.capacity);
    UartTxLease blocked{};
    assert(!UartTxPool_Acquire(1, &blocked));
    assert(!UartTxPool_Commit(&lease, UART_TX_POOL_BYTES + 1));
    assert(UartTxPool_Commit(&lease, UART_TX_POOL_BYTES));
    assert(lease.data == nullptr);
    auto duplicate = stale;
    assert(!UartTxPool_Commit(&duplicate, 1));
    assert(!UartTxPool_Cancel(&duplicate));
    assert(UartTxPool_Begin(&message));
    assert(message.data == address); // exact original storage, not a copy
    assert(message.length == UART_TX_POOL_BYTES);
    assert(!UartTxPool_Acquire(1, &blocked)); // still pinned during DMA
    assert(!UartTxPool_Begin(&message)); // single in-flight message
    for (size_t i = 0; i < message.length; ++i) assert(message.data[i] == 0x5a);
    assert(UartTxPool_Finish(&message));
    assert(!UartTxPool_Finish(&message));
    assert(UartTxPool_ReservedBlocks() == 0);
    assert(UartTxPool_QueuedBytes() == 0);
    assert(UartTxPool_Acquire(1, &lease));
    duplicate = stale;
    assert(!UartTxPool_Cancel(&duplicate));
    assert(!UartTxPool_Commit(&duplicate, 1));
    auto forged = lease;
    forged.capacity = UART_TX_POOL_BYTES;
    assert(!UartTxPool_Commit(&forged, UART_TX_POOL_BYTES));
    assert(UartTxPool_Cancel(&lease));
    assert(UartTxPool_ReservedBlocks() == 0);

    // An unfinished reservation must NOT block a different producer's commit.
    UartTxLease slow{}, fast{};
    assert(UartTxPool_Acquire(10, &slow));
    assert(UartTxPool_Acquire(10, &fast));
    fast.data[0] = 42;
    const auto *fastAddress = fast.data;
    assert(UartTxPool_Commit(&fast, 1));
    assert(UartTxPool_Begin(&message));
    assert(message.data == fastAddress && message.data[0] == 42);
    assert(UartTxPool_Finish(&message));
    assert(UartTxPool_Cancel(&slow));

    // Fragmentation is reported without moving payloads or partial reservation.
    std::vector<UartTxLease> blocks(32);
    for (auto &block : blocks) assert(UartTxPool_Acquire(1, &block));
    for (size_t i = 0; i < blocks.size(); i += 2) assert(UartTxPool_Cancel(&blocks[i]));
    assert(!UartTxPool_Acquire(257, &lease));
    for (size_t i = 1; i < blocks.size(); i += 2) assert(UartTxPool_Cancel(&blocks[i]));
    assert(UartTxPool_ReservedBlocks() == 0);
}

static void ConcurrentStress()
{
    constexpr unsigned producers = 4;
    constexpr unsigned perProducer = 15000;
    UartTxPool_Init();
    std::atomic<unsigned> started{0};
    std::vector<std::thread> workers;
    for (unsigned p = 0; p < producers; ++p) {
        workers.emplace_back([p, &started] {
            started.fetch_add(1);
            while (started.load() != producers) std::this_thread::yield();
            for (unsigned seq = 0; seq < perProducer; ++seq) {
                UartTxLease lease{};
                const size_t size = 12U + (seq * 37U + p * 19U) % 2017U;
                while (!UartTxPool_Acquire(size, &lease)) std::this_thread::yield();
                // Serialize directly into final DMA storage, never a local packet.
                lease.data[0] = static_cast<uint8_t>(p);
                for (unsigned k = 0; k < 4; ++k)
                    lease.data[1 + k] = static_cast<uint8_t>(seq >> (8U * k));
                for (size_t k = 5; k < size; ++k)
                    lease.data[k] = static_cast<uint8_t>(p * 11U + seq + k);
                if ((seq % 31U) == 0U) std::this_thread::yield();
                assert(UartTxPool_Commit(&lease, size));
            }
        });
    }
    unsigned next[producers]{};
    unsigned consumed = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
    while (consumed < producers * perProducer) {
        UartTxMessage message{};
        if (!UartTxPool_Begin(&message)) {
            assert(std::chrono::steady_clock::now() < deadline);
            std::this_thread::yield();
            continue;
        }
        const unsigned p = message.data[0];
        assert(p < producers);
        unsigned seq = 0;
        for (unsigned k = 0; k < 4; ++k) seq |= unsigned(message.data[1 + k]) << (8U * k);
        assert(seq == next[p]++); // publication FIFO per producer
        for (size_t k = 5; k < message.length; ++k)
            assert(message.data[k] == static_cast<uint8_t>(p * 11U + seq + k));
        if (consumed % 47U == 0U) std::this_thread::yield(); // slow DMA consumer
        assert(UartTxPool_Finish(&message));
        ++consumed;
    }
    for (auto &thread : workers) thread.join();
    for (const auto count : next) assert(count == perProducer);
    assert(UartTxPool_ReservedBlocks() == 0);
    assert(UartTxPool_QueuedBytes() == 0);
    std::printf("PASS: 4 producers, 60000 messages; payload, FIFO, lifetime, reuse\n");
}

static void CursorContracts()
{
    UartRxCursor cursor{};
    UartRxCursor_Init(&cursor, 1024);
    assert(UartRxCursor_Position(0, 511, 1024) == 511);
    assert(UartRxCursor_Position(0, 512, 1024) == 512); // pending HT
    assert(UartRxCursor_Position(1, 512, 1024) == 512);
    assert(UartRxCursor_Position(1, 0, 1024) == 1024); // pending TC
    assert(UartRxCursor_Position(2, 0, 1024) == 1024);
    assert(UartRxCursor_Update(&cursor, 1023) == 1023);
    assert(UartRxCursor_Update(&cursor, 1024) == 0);
    assert(cursor.dropped == 1024 && cursor.gaps == 1);
    assert(UartRxCursor_Update(&cursor, 1100) == 76);
    cursor.consumed += 40;
    UartRxCursor_Gap(&cursor);
    assert(cursor.dropped == 1060 && cursor.gaps == 2);
    cursor.consumed = cursor.produced = UINT32_MAX - 3U;
    const auto total = cursor.total;
    assert(UartRxCursor_Update(&cursor, 5) == 9);
    assert(cursor.total == total + 9);
}

static void SaveLine(const char *line, void *context)
{
    static_cast<std::vector<std::string> *>(context)->emplace_back(line);
}

static void ParserContracts()
{
    UartLineParser parser{};
    UartLineParser_Init(&parser);
    std::vector<std::string> lines;
    const auto feed = [&](const std::string &text) {
        for (const auto byte : text)
            UartLineParser_Byte(&parser, static_cast<uint8_t>(byte), SaveLine, &lines);
    };
    feed("1 PING\r\n2 STAX\bTUS\n");
    assert(lines.size() == 2 && lines[0] == "1 PING" && lines[1] == "2 STATUS");
    feed("3 STA");
    UartLineParser_Gap(&parser);
    feed("RT\n4 PING\n");
    assert(lines.size() == 3 && lines.back() == "4 PING");
    feed(std::string(400, 'A') + "5 START\n6 PING\n");
    assert(lines.size() == 4 && lines.back() == "6 PING");
}

int main()
{
    PoolContracts();
    CursorContracts();
    ParserContracts();
    ConcurrentStress();
    std::puts("PASS: pool bounds/stale leases/fragmentation, RX wrap/gap, parser resync");
}
