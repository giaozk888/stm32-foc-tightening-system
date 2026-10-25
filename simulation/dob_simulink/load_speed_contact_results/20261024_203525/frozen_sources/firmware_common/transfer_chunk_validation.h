#ifndef TRANSFER_CHUNK_VALIDATION_H
#define TRANSFER_CHUNK_VALIDATION_H
#include "pw_protobuf/decoder.h"

namespace transfer_can {
// Shape guard for this bounded, pinned V2 schema. Upstream Chunk::Parse may
// accept session_id without type, or Completion without status; later value()
// accesses assume those fields exist. Validate before invoking the engine.
inline bool validV2Chunk(pw::ConstByteSpan bytes) {
    if (bytes.empty() || bytes.size() > 96) return false;
    pw::protobuf::Decoder decoder(bytes);
    pw::Status status;
    uint32_t seen = 0, type = 0, session = 0, desired = 0, version = 0;
    while ((status = decoder.Next()).ok()) {
        const uint32_t field = decoder.FieldNumber();
        if (field == 0 || field > 15 || (seen & (1U << field))) return false;
        seen |= 1U << field;
        if (field == 6) {
            pw::ConstByteSpan payload;
            if (!decoder.ReadBytes(&payload).ok() || payload.size() > 32) return false;
        } else if (field == 7) {
            uint64_t remaining;
            if (!decoder.ReadUint64(&remaining).ok() || remaining > 16U * 191U) return false;
        } else {
            uint32_t value;
            if (!decoder.ReadUint32(&value).ok()) return false;
            switch (field) {
                case 2: if (value > 64) return false; break;
                case 3: if (!value || value > 96) return false; break;
                case 4: if (value > 1000000) return false; break;
                case 5: case 15: if (value > 16U * 191U) return false; break;
                case 8: if (value > 16) return false; break;
                case 9: if (value > 16U * 191U + 64) return false; break;
                case 10: type = value; break;
                case 12: session = value; break;
                case 13: version = value; break;
                case 14: desired = value; break;
                default: break;
            }
        }
    }
    if (!status.IsOutOfRange() || !(seen & (1U << 10)) || type > 7 ||
        ((seen & (1U << 13)) && version != 2) ||
        ((seen & (1U << 12)) && (seen & (1U << 14)))) return false;
    if (type == 1) // V2 Start must name a resource and desired session.
        return desired && (seen & (1U << 11)) && version == 2;
    if (!session || !(seen & (1U << 12))) return false;
    return type != 4 || (seen & (1U << 8)); // Completion requires status, including OK=0.
}
}
#endif
