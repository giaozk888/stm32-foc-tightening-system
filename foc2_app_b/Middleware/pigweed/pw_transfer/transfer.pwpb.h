#pragma once

// Minimal generated-compatible binding for pw_transfer/transfer.proto Chunk.
// It exposes the enum, fields and encoder API consumed by pw_transfer::Chunk.
#include <cstdint>
#include "pw_bytes/span.h"
#include "pw_protobuf/encoder.h"
#include "pw_status/status.h"

namespace pw::transfer::pwpb::Chunk {
enum class Type : uint32_t {
  kData = 0,
  kStart = 1,
  kParametersRetransmit = 2,
  kParametersContinue = 3,
  kCompletion = 4,
  kCompletionAck = 5,
  kStartAck = 6,
  kStartAckConfirmation = 7,
};
enum class Fields : uint32_t {
  kTransferId = 1, kPendingBytes = 2, kMaxChunkSizeBytes = 3,
  kMinDelayMicroseconds = 4, kOffset = 5, kData = 6,
  kRemainingBytes = 7, kStatus = 8, kWindowEndOffset = 9,
  kType = 10, kResourceId = 11, kSessionId = 12,
  kProtocolVersion = 13, kDesiredSessionId = 14, kInitialOffset = 15,
};
class MemoryEncoder : public protobuf::MemoryEncoder {
 public:
  explicit MemoryEncoder(ByteSpan b) : protobuf::MemoryEncoder(b) {}
  Status WriteTransferId(uint32_t v) { return WriteUint32(1, v); }
  Status WritePendingBytes(uint32_t v) { return WriteUint32(2, v); }
  Status WriteMaxChunkSizeBytes(uint32_t v) { return WriteUint32(3, v); }
  Status WriteMinDelayMicroseconds(uint32_t v) { return WriteUint32(4, v); }
  Status WriteOffset(uint64_t v) { return WriteUint64(5, v); }
  Status WriteData(ConstByteSpan v) { return WriteBytes(6, v); }
  Status WriteRemainingBytes(uint64_t v) { return WriteUint64(7, v); }
  Status WriteStatus(uint32_t v) { return WriteUint32(8, v); }
  Status WriteWindowEndOffset(uint32_t v) { return WriteUint32(9, v); }
  Status WriteType(Type v) { return WriteUint32(10, static_cast<uint32_t>(v)); }
  Status WriteResourceId(uint32_t v) { return WriteUint32(11, v); }
  Status WriteSessionId(uint32_t v) { return WriteUint32(12, v); }
  Status WriteProtocolVersion(uint32_t v) { return WriteUint32(13, v); }
  Status WriteDesiredSessionId(uint32_t v) { return WriteUint32(14, v); }
  Status WriteInitialOffset(uint64_t v) { return WriteUint64(15, v); }
};
}  // namespace pw::transfer::pwpb::Chunk
