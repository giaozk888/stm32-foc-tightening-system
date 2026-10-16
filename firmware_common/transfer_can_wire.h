#ifndef TRANSFER_CAN_WIRE_H
#define TRANSFER_CAN_WIRE_H
#include <cstdint>

// A streaming RPC call spans many CAN packets. Each packet gets a fresh ID;
// this is not the RPC call_id or the Transfer session_id. Low IDs are unary.
namespace transfer_can {
constexpr std::uint16_t streamBit = 0x8000;
constexpr std::uint16_t counterMask = 0x7fff;
constexpr bool isStream(std::uint16_t id) { return (id & streamBit) != 0; }
constexpr std::uint16_t packetId(std::uint32_t sequence) {
    return streamBit | (sequence & counterMask);
}
}
#endif
