#include "can_rpc_transport.h"
#include "rpc_readonly_wire.h"
#include <cassert>
#include <cstring>
#include <random>
#include <iostream>
#include "test_assert.h"

static CanRpcResult feed(CanRpcReceiver &rx, const std::uint8_t *data, std::uint32_t now = 0) {
    return CanRpc_Feed(&rx, CAN_RPC_REQUEST_ID, CAN_RPC_REQUEST_ID, 0, 0, 0, 0, 8, data, now);
}
int main() {
    assert(CanRpc_Crc16(reinterpret_cast<const std::uint8_t*>("123456789"), 9) == 0x29B1);
    std::mt19937 random(474);
    for (unsigned length = 1; length <= CAN_RPC_MAX_PACKET; ++length) {
        CanRpcPacket packet{}; packet.transaction = 123; packet.length = length;
        for (unsigned i = 0; i < length; ++i) packet.bytes[i] = static_cast<std::uint8_t>(random());
        CanRpcReceiver rx{}; std::uint8_t frame[8];
        for (std::size_t index = 0; index < CanRpc_FrameCount(length); ++index) {
            assert(CanRpc_EncodeFrame(&packet, index, frame));
            const auto result = feed(rx, frame, 0xFFFFFF00U + static_cast<std::uint32_t>(index * 75U));
            assert(result == (index + 1 == CanRpc_FrameCount(length) ? CAN_RPC_COMPLETE : CAN_RPC_PARTIAL));
        }
        assert(rx.packet.length == length && std::memcmp(packet.bytes, rx.packet.bytes, length) == 0);
        assert(!CanRpc_EncodeFrame(&packet, CanRpc_FrameCount(length), frame));
    }
    CanRpcPacket p{}; p.transaction = 8; p.length = 5; p.bytes[0] = 1;
    std::uint8_t start[8], first[8], last[8];
    assert(CanRpc_EncodeFrame(&p, 0, start) && CanRpc_EncodeFrame(&p, 1, first) && CanRpc_EncodeFrame(&p, 2, last));
    CanRpcReceiver r{};
    assert(feed(r, first) == CAN_RPC_IGNORED);
    assert(feed(r, start) == CAN_RPC_PARTIAL);
    assert(feed(r, start, 400) == CAN_RPC_BUSY);
    assert(CanRpc_Expire(&r, 500)); // repeated START did not extend deadline
    assert(feed(r, start, 600) == CAN_RPC_PARTIAL);
    assert(feed(r, last, 601) == CAN_RPC_INVALID); // missing/out-of-order
    assert(feed(r, start, 700) == CAN_RPC_PARTIAL);
    assert(feed(r, first, 701) == CAN_RPC_PARTIAL);
    assert(feed(r, first, 702) == CAN_RPC_INVALID); // duplicate fragment fails closed
    assert(feed(r, start, 800) == CAN_RPC_PARTIAL);
    first[1] ^= 1; assert(feed(r, first, 801) == CAN_RPC_IGNORED); first[1] ^= 1;
    assert(feed(r, first, 802) == CAN_RPC_PARTIAL);
    last[7] = 1; assert(feed(r, last, 803) == CAN_RPC_INVALID); last[7] = 0;
    assert(feed(r, start, 900) == CAN_RPC_PARTIAL);
    first[4] ^= 1; assert(feed(r, first, 901) == CAN_RPC_PARTIAL); first[4] ^= 1;
    assert(feed(r, last, 902) == CAN_RPC_BAD_CRC);
    assert(feed(r, start, 1000) == CAN_RPC_PARTIAL);
    assert(feed(r, first, 1001) == CAN_RPC_PARTIAL && feed(r, last, 1002) == CAN_RPC_COMPLETE);
    assert(feed(r, start, 1003) == CAN_RPC_IGNORED); // completed transaction replay
    CanRpc_Reset(&r); assert(feed(r, start, 0) == CAN_RPC_PARTIAL);
    assert(feed(r, first, 500) == CAN_RPC_TIMED_OUT);
    for (unsigned which = 0; which < 5; ++which) {
        CanRpc_Reset(&r);
        assert(CanRpc_Feed(&r, CAN_RPC_REQUEST_ID, CAN_RPC_REQUEST_ID, which == 0,
            which == 1, which == 2, which == 3, which == 4 ? 7 : 8, start, 0) == CAN_RPC_INVALID);
    }
    assert(CanRpc_FrameCount(0) == 0 && CanRpc_FrameCount(129) == 0);
    start[3] = 129; assert(feed(r, start) == CAN_RPC_INVALID); start[3] = 5;
    start[7] = 2; assert(feed(r, start) == CAN_RPC_INVALID); start[7] = 1;
    std::uint8_t request[128];
    const auto n = rpc_readonly::encodeRequest(rpc_readonly::status, 1, nullptr, 0, request, sizeof(request));
    rpc_readonly::Packet decoded;
    assert(n && rpc_readonly::decode(request, n, decoded) && rpc_readonly::requestAllowed(decoded));
    request[n] = 0x10; request[n+1] = 2;
    assert(!rpc_readonly::decode(request, n+2, decoded)); // duplicate field
    for (unsigned i = 0; i < 100000; ++i) {
        std::uint8_t fuzz[128]{}; const auto size = 1U + random() % 128U;
        for (unsigned k = 0; k < size; ++k) fuzz[k] = static_cast<std::uint8_t>(random());
        (void)rpc_readonly::decode(fuzz, size, decoded);
        (void)CanRpc_Feed(&r, CAN_RPC_REQUEST_ID, CAN_RPC_REQUEST_ID, 0, 0, 0, 0, 8, fuzz, i);
    }
    std::cout << "Transport lengths 1..128, frame faults, wraparound, strict protobuf and 100000 fuzz cases PASS\n";
}
