#ifndef UART_FIRMWARE_TRANSFER_WIRE_H
#define UART_FIRMWARE_TRANSFER_WIRE_H
#include "uart_firmware_transfer.h"
#include "pw_protobuf/decoder.h"
#include "pw_rpc/internal/hash.h"
#include "pw_rpc/internal/packet.h"
namespace uart_fw {
constexpr uint32_t service = pw::rpc::internal::Hash("pw.transfer.Transfer");
constexpr uint32_t write = pw::rpc::internal::Hash("Write");
// Shape/size guard only. All handshake/window/retry state is upstream-owned.
inline bool validChunk(pw::ConstByteSpan bytes) {
    if (bytes.empty() || bytes.size() > UART_FW_PACKET)
        return false;
    pw::protobuf::Decoder d(bytes);
    uint32_t seen = 0, type = 0, session = 0, desired = 0, version = 0;
    pw::Status status;
    while ((status = d.Next()).ok()) {
        const auto f = d.FieldNumber();
        if (!f || f > 15 || (seen & (1U << f)))
            return false;
        seen |= 1U << f;
        if (f == 6) {
            pw::ConstByteSpan data;
            if (!d.ReadBytes(&data).ok() || data.size() > 64)
                return false;
        } else if (f == 7) {
            uint64_t value;
            if (!d.ReadUint64(&value).ok() || value > UART_FW_CAPACITY)
                return false;
        } else {
            uint32_t value;
            if (!d.ReadUint32(&value).ok())
                return false;
            switch (f) {
            case 2:
                if (value > 64)
                    return false;
                break;
            case 3:
                if (!value || value > UART_FW_PACKET)
                    return false;
                break;
            case 4:
                if (value > 1000000)
                    return false;
                break;
            case 5:
            case 15:
                if (value > UART_FW_CAPACITY)
                    return false;
                break;
            case 8:
                if (value > 16)
                    return false;
                break;
            case 9:
                if (value > UART_FW_CAPACITY + 64)
                    return false;
                break;
            case 10:
                type = value;
                break;
            case 11:
                if (value != UART_FW_RESOURCE)
                    return false;
                break;
            case 12:
                session = value;
                break;
            case 13:
                version = value;
                break;
            case 14:
                desired = value;
                break;
            default:
                break;
            }
        }
    }
    if (!status.IsOutOfRange() || !(seen & (1U << 10)) || type > 7 ||
        ((seen & (1U << 13)) && version != 2) || ((seen & (1U << 12)) && (seen & (1U << 14))))
        return false;
    if (type == 1)
        return desired && (seen & (1U << 11)) && version == 2 && !(seen & (1U << 6));
    return session && (seen & (1U << 12)) && (type != 4 || (seen & (1U << 8)));
}
inline bool identity(const pw::rpc::internal::Packet &p) {
    return p.channel_id() == UART_FW_CHANNEL && p.service_id() == service &&
           p.method_id() == write && p.call_id();
}
} // namespace uart_fw
#endif
