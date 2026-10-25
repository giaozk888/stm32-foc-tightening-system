#ifndef LOG_TRANSFER_WIRE_H
#define LOG_TRANSFER_WIRE_H
#include "rpc_readonly_wire.h"

/* Historical unary wire codec: not used by current firmware/HMI builds.
 * Bounded V2 Chunk subset for foc.ReadOnly.ReadLogChunk (unary pull).
 * This is NOT the official streaming Transfer.Read protocol. The MCU uses
 * upstream Chunk::Parse/Encode; this small desktop codec is cross-tested. */
namespace log_transfer {
constexpr std::uint32_t resource = 3, block = 32, historyCapacity = 16;
constexpr std::uint32_t maxBytes = historyCapacity * 191;
constexpr std::uint32_t Data = 0, Start = 1, Continue = 3, Completion = 4, CompletionAck = 5, StartAck = 6;
struct Chunk {
    std::uint32_t type = 0, session = 0, resourceId = 0, version = 0, offset = 0;
    std::uint32_t remaining = 0, status = 0, maxChunk = 0, fields = 0;
    const std::uint8_t *data = nullptr;
    std::size_t size = 0;
    bool has(unsigned field) const { return fields & (1U << field); }
};
inline bool decode(const std::uint8_t *bytes, std::size_t size, Chunk &out) {
    if (!bytes || !size || size > 76) return false;
    Chunk parsed; std::size_t pos = 0;
    while (pos < size) {
        std::uint32_t key, value;
        if (!rpc_readonly::varint(bytes, size, pos, key)) return false;
        const auto field = key >> 3, wire = key & 7U;
        if (field != 3 && field != 5 && field != 6 && field != 7 && field != 8 &&
            field != 9 && field != 10 && field != 11 && field != 12 && field != 13) return false;
        if (parsed.has(field)) return false;
        parsed.fields |= 1U << field;
        if (field == 6) {
            if (wire != 2 || !rpc_readonly::varint(bytes, size, pos, value) || value > size - pos || value > block) return false;
            parsed.data = bytes + pos; parsed.size = value; pos += value; continue;
        }
        if (wire != 0 || !rpc_readonly::varint(bytes, size, pos, value)) return false;
        switch (field) {
            case 3: parsed.maxChunk = value; break;
            case 5: parsed.offset = value; break;
            case 7: parsed.remaining = value; break;
            case 8: parsed.status = value; break;
            case 9: if (value > maxBytes) return false; break;
            case 10: parsed.type = value; break;
            case 11: parsed.resourceId = value; break;
            case 12: parsed.session = value; break;
            case 13: parsed.version = value; break;
            default: return false;
        }
    }
    if (!parsed.has(10) || !parsed.session || !parsed.has(12) || parsed.type > 7 ||
        (parsed.has(13) && parsed.version != 2) || parsed.offset > maxBytes || parsed.remaining > maxBytes) return false;
    out = parsed; return true;
}
inline bool requestAllowed(const Chunk &c) {
    const std::uint32_t common = (1U << 10) | (1U << 12);
    if (c.type == Start)
        return c.fields == (common | (1U << 11) | (1U << 13)) && c.resourceId == resource && c.version == 2;
    if (c.type == Continue)
        return (c.fields & ~(common | (1U << 3) | (1U << 5))) == 0 && c.has(3) && c.maxChunk == block;
    if (c.type == Completion)
        return c.fields == (common | (1U << 8)) && (c.status == 0 || c.status == 1);
    return false; // Reject incoming data, legacy IDs, writes and arbitrary resources.
}
inline std::size_t encodeRequest(std::uint32_t type, std::uint32_t session, std::uint32_t offset,
    std::uint32_t status, std::uint8_t *out, std::size_t capacity) {
    if (!out || capacity < 32 || !session || offset > maxBytes || status > 1 ||
        (type != Start && type != Continue && type != Completion)) return 0;
    std::size_t pos = 0;
    auto field = [&](unsigned number, std::uint32_t value) {
        out[pos++] = static_cast<std::uint8_t>(number << 3);
        do { out[pos++] = static_cast<std::uint8_t>((value & 127U) | (value > 127 ? 128U : 0)); value >>= 7; } while (value);
    };
    field(12, session); field(10, type);
    if (type == Start) { field(11, resource); field(13, 2); }
    if (type == Continue) { field(3, block); if (offset) field(5, offset); }
    if (type == Completion) field(8, status);
    return pos;
}
}
#endif
