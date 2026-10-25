#ifndef RPC_READONLY_WIRE_H
#define RPC_READONLY_WIRE_H
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string_view>
#include "can_rpc_transport.h"
#include "rpc_readonly.h"

/* Small raw protobuf client codec for the pinned Pigweed RpcPacket schema.
 * Not a replacement for pw_rpc Server; verified against its real codec. */
namespace rpc_readonly {
constexpr std::uint32_t hash(std::string_view text) {
    std::uint32_t result = static_cast<std::uint32_t>(text.size()), coefficient = 65599U;
    for (char c : text) { result += coefficient * static_cast<unsigned char>(c); coefficient *= 65599U; }
    return result;
}
constexpr std::uint32_t channel = 2U;
constexpr std::uint32_t service = hash("foc.ReadOnly");
constexpr std::uint32_t ping = hash("Ping"), status = hash("GetStatus");
constexpr std::uint32_t params = hash("GetParams"), diagnostics = hash("GetDiagnostics");
constexpr std::uint32_t logChunk = hash("ReadLogChunk");
inline bool allowed(std::uint32_t method) {
    return method == ping || method == status || method == params || method == diagnostics;
}
inline void put32(std::uint8_t *out, std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) out[i] = static_cast<std::uint8_t>(value >> (8U * i));
}
inline std::uint32_t get32(const std::uint8_t *in) {
    return std::uint32_t(in[0]) | (std::uint32_t(in[1]) << 8) |
        (std::uint32_t(in[2]) << 16) | (std::uint32_t(in[3]) << 24);
}
struct Packet {
    std::uint32_t type = 0, channel_id = 0, service_id = 0, method_id = 0, call_id = 0, status = 0;
    const std::uint8_t *payload = nullptr;
    std::size_t payload_size = 0;
};
inline bool varint(const std::uint8_t *data, std::size_t size, std::size_t &pos, std::uint32_t &out) {
    out = 0U;
    for (unsigned n = 0; n < 5; ++n) {
        if (pos == size) return false;
        const auto byte = data[pos++];
        if (n == 4 && (byte & 0xF0U)) return false;
        out |= std::uint32_t(byte & 0x7FU) << (7U * n);
        if (!(byte & 0x80U)) return true;
    }
    return false;
}
inline bool decode(const std::uint8_t *data, std::size_t size, Packet &out) {
    if (!data || size == 0 || size > CAN_RPC_MAX_PACKET) return false;
    Packet parsed; std::size_t pos = 0; unsigned seen = 0;
    while (pos < size) {
        std::uint32_t key, value = 0;
        if (!varint(data, size, pos, key)) return false;
        const auto field = key >> 3, wire = key & 7U;
        if (field < 1 || field > 7 || (seen & (1U << field))) return false;
        seen |= 1U << field;
        if (field == 3 || field == 4) {
            if (wire != 5 || size - pos < 4) return false;
            value = get32(data + pos); pos += 4;
        } else if (field == 5) {
            if (wire != 2 || !varint(data, size, pos, value) || value > size - pos) return false;
            parsed.payload = data + pos; parsed.payload_size = value; pos += value;
        } else if (wire != 0 || !varint(data, size, pos, value)) return false;
        switch (field) {
            case 1: parsed.type = value; break;
            case 2: parsed.channel_id = value; break;
            case 3: parsed.service_id = value; break;
            case 4: parsed.method_id = value; break;
            case 6: parsed.status = value; break;
            case 7: parsed.call_id = value; break;
            default: break;
        }
    }
    /* Type/status may be omitted protobuf defaults; identities must be explicit. */
    if ((seen & 0x9CU) != 0x9CU || !parsed.call_id) return false;
    out = parsed; return true;
}
inline bool requestAllowed(const Packet &p) {
    return p.type == 0 && p.status == 0 && p.channel_id == channel && p.service_id == service &&
        p.call_id != 0 && allowed(p.method_id) &&
        (p.method_id == ping ? p.payload_size <= 16 : p.payload_size == 0);
}
inline std::size_t encodeRequest(std::uint32_t method, std::uint32_t call,
    const std::uint8_t *payload, std::size_t length, std::uint8_t *out, std::size_t capacity) {
    if (!out || !call || !allowed(method) || length > 64 || (length && !payload) ||
        (method == ping ? length > 16 : length != 0)) return 0;
    if (capacity < 23 + length) return 0;
    std::size_t pos = 0;
    out[pos++] = 0x08; out[pos++] = 0;
    out[pos++] = 0x10; out[pos++] = channel;
    out[pos++] = 0x1D; put32(out + pos, service); pos += 4;
    out[pos++] = 0x25; put32(out + pos, method); pos += 4;
    if (length) { out[pos++] = 0x2A; out[pos++] = static_cast<std::uint8_t>(length); std::memcpy(out + pos, payload, length); pos += length; }
    out[pos++] = 0x38;
    do { out[pos++] = static_cast<std::uint8_t>((call & 0x7FU) | (call > 127 ? 0x80U : 0)); call >>= 7; } while (call);
    return pos;
}
}
#endif
