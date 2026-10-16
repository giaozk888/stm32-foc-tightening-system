#include "transfer_client.h"
#include "pw_buffer_test_heap.h"
#include "router_network.h"
#include "rpc_readonly_wire.h"
#include "pw_rpc/internal/packet.h"
#include "pw_transfer/internal/chunk.h"
#include <cassert>
#include <chrono>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
#include "pw_log_backend.h"
#include "../can_rpc_host/test_assert.h"
extern "C" void TransferTest_SetHistory(const char *, size_t);
extern "C" void TransferTest_ClearHistory(void);
static std::recursive_mutex critical;
extern "C" void RPC_TestLock() {
    critical.lock();
}
extern "C" void RPC_TestUnlock() {
    critical.unlock();
}
static std::mutex txMutex;
static std::deque<RouterPacket_t> replies;
static uint8_t tx(const RouterPacket_t *packet) {
    std::lock_guard<std::mutex> lock(txMutex);
    assert(replies.size() < 64);
    replies.push_back(*packet);
    return 1;
}
static bool pop(RouterPacket_t &frame) {
    std::lock_guard<std::mutex> lock(txMutex);
    if (replies.empty())
        return false;
    frame = replies.front();
    replies.pop_front();
    return true;
}
static uint32_t now() {
    return uint32_t(std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::steady_clock::now().time_since_epoch())
                        .count());
}
static void ingress(const RouterPacket_t &frame, RouterPort_t port = ROUTER_PORT_UART1) {
    char text[321];
    assert(Router_EncodeAsciiFrame(&frame, text, sizeof(text)));
    assert(Router_SubmitAsciiLine(port, text));
    Router_Service(8);
}
static void genericForwarding() {
    assert(Router_SubmitAsciiLine(ROUTER_PORT_ESP32, "@R1 5 65535 3 400 8 5 HELLO"));
    Router_Service(8);
    RouterPacket_t frame;
    while (pop(frame)) {
    }
    uint8_t bytes[1024];
    for (unsigned i = 0; i < 1024; ++i)
        bytes[i] = uint8_t(i);
    rn_transfer_receiver_t receiver{};
    rn_transfer_view_t view;
    for (unsigned offset = 0; offset < 1024; offset += 88) {
        frame = {};
        frame.src = 4;
        frame.dst = 5;
        frame.type = 9;
        frame.ttl = 8;
        frame.seq = uint16_t(500 + offset);
        frame.length = uint16_t(
            rn_transfer_format(20, bytes, 1024, offset, frame.payload, sizeof(frame.payload)));
        ingress(frame);
        bool found = false;
        while (pop(frame))
            if (frame.type == 9) {
                assert(frame.dst == 5 && frame.ttl == 7);
                auto result = rn_transfer_feed(&receiver, 4, 5, 0, 0, frame.payload, 0, &view);
                assert(result ==
                       (offset + 88 >= 1024 ? RN_TRANSFER_COMPLETE : RN_TRANSFER_PENDING));
                found = true;
            }
        assert(found);
    }
    assert(view.size == 1024 && !memcmp(view.data, bytes, 1024));
    Router_ForgetPort(ROUTER_PORT_UART1);
    Router_ForgetPort(ROUTER_PORT_ESP32);
}
static void roundtrip(const std::string &history, unsigned resource, int dropType = -1) {
    TransferTest_SetHistory(history.data(), history.size());
    RouterTransferClient client(4);
    assert(client.begin(resource));
    bool dropped = false;
    const auto deadline = now() + 12000;
    while (!client.done() && int32_t(deadline - now()) > 0) {
        RouterPacket_t frame;
        while (client.pop(frame))
            ingress(frame);
        PW_RouterTransfer_Tick(now());
        while (Router_LocalReadPacket(&frame)) {
            if (frame.type == 9)
                assert(PW_RouterTransfer_Process(&frame, now()));
        }
        while (pop(frame)) {
            if (frame.type != 9)
                continue;
            if (!dropped && dropType >= 0) {
                rn_transfer_fragment_t f;
                assert(rn_transfer_parse(frame.payload, &f));
                rpc_readonly::Packet packet;
                if (!f.offset && f.size == f.total &&
                    rpc_readonly::decode(f.data, f.size, packet)) {
                    auto chunk = pw::transfer::internal::Chunk::Parse(pw::ConstByteSpan(
                        reinterpret_cast<const std::byte *>(packet.payload), packet.payload_size));
                    if (chunk.ok() && int(chunk->type()) == dropType) {
                        dropped = true;
                        continue;
                    }
                }
            }
            assert(client.receive(frame, now()));
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    assert(client.done() && client.success());
    const auto bytes = client.data();
    if (resource == 3)
        assert(bytes.size() == history.size() &&
               !memcmp(bytes.data(), history.data(), bytes.size()));
    else {
        assert(bytes.size() == 40);
        const auto *p = reinterpret_cast<const uint8_t *>(bytes.data());
        assert(!memcmp(p, "ENC1", 4) && rpc_readonly::get32(p + 8) == 9 &&
               rpc_readonly::get32(p + 28) == (1234U | 1234U << 16) &&
               rn_transfer_crc32(p, 36) == rpc_readonly::get32(p + 36));
    }
    if (dropType >= 0)
        assert(dropped);
    // Disconnect cleanup is processed by the real thread before the next session.
    Router_ForgetPort(ROUTER_PORT_UART1);
    PW_RouterTransfer_Tick(now());
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
}
static void rejectWrites() {
    std::array<std::byte, 128> storage;
    for (uint32_t method : {rpc_readonly::hash("Write"), rpc_readonly::hash("GetResourceStatus")}) {
        pw::rpc::internal::Packet packet(pw::rpc::internal::pwpb::PacketType::REQUEST,
                                         RN_TRANSFER_CHANNEL_BASE + 4,
                                         rpc_readonly::hash("pw.transfer.Transfer"), method, 7);
        auto encoded = packet.Encode(storage);
        assert(encoded.ok());
        RouterPacket_t frame{};
        frame.src = 4;
        frame.dst = 1;
        frame.type = 9;
        frame.ttl = 8;
        frame.seq = uint16_t(method);
        frame.ingress_port = ROUTER_PORT_UART1;
        frame.ingress_epoch = Router_PortEpoch(frame.ingress_port);
        frame.length =
            uint16_t(rn_transfer_format(1, reinterpret_cast<const uint8_t *>(encoded->data()),
                                        encoded->size(), 0, frame.payload, sizeof(frame.payload)));
        assert(!PW_RouterTransfer_Process(&frame, now()));
    }
}
static int stdioServer() {
    PW_RouterTransfer_Tick(now());
    std::thread server(PW_RouterTransfer_Run);
    const std::string history = std::string(400, 'R') + "\nRouter official history\n";
    TransferTest_SetHistory(history.data(), history.size());
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line != "TICK" && rn_line_allowed(line.c_str()))
            (void)Router_SubmitAsciiLine(ROUTER_PORT_UART1, line.c_str());
        Router_Service(8);
        PW_RouterTransfer_Tick(now());
        RouterPacket_t frame;
        while (Router_LocalReadPacket(&frame))
            if (frame.type == 9)
                (void)PW_RouterTransfer_Process(&frame, now());
        while (pop(frame))
            if (frame.type == 9) {
                char text[321];
                assert(Router_EncodeAsciiFrame(&frame, text, sizeof(text)));
                std::cout << text << std::endl;
            }
    }
    TransferTest_ClearHistory();
    PW_RouterTransfer_Stop();
    server.join();
    return 0;
}
int main(int argc, char **argv) {
    assert(Router_Init(1));
    PwLogStore_Init();
    Router_RegisterPortTx(ROUTER_PORT_UART1, tx);
    Router_RegisterPortTx(ROUTER_PORT_ESP32, tx);
    if (argc == 2 && std::string(argv[1]) == "--stdio-server")
        return stdioServer();
    genericForwarding();
    PW_RouterTransfer_Tick(now());
    std::thread server(PW_RouterTransfer_Run);
    rejectWrites();
    std::string maximum(3056, 'x');
    for (size_t i = 0; i < maximum.size(); ++i)
        maximum[i] = char(' ' + i % 90);
    roundtrip(maximum, 3);
    roundtrip("", 3);
    roundtrip("history line\n", 3, int(pw::transfer::internal::Chunk::Type::kStartAck));
    roundtrip("history line\n", 3, int(pw::transfer::internal::Chunk::Type::kData));
    roundtrip("history line\n", 3, int(pw::transfer::internal::Chunk::Type::kCompletionAck));
    roundtrip("", 4);
    TransferTest_ClearHistory();
    PW_RouterTransfer_Stop();
    server.join();
    assert(PwLogStore_Used() == 0);
    assert(PW_BufferTest_LiveAllocations() == 0);
    std::cout << "ROUTER TRANSFER PASS: A/B actual Router + official Client/Service/Thread; "
                 "1024-byte forwarding, max/empty log, lost handshake/data/final ACK, encoder CRC, "
                 "no writes\n";
}
