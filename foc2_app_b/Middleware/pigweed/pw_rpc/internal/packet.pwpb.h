#pragma once

// Minimal binding for pw_rpc/internal/packet.proto; avoids a host protoc
// dependency while exposing exactly the generated API used by pw_rpc core.
#include <cstdint>
#include "pw_bytes/span.h"
#include "pw_protobuf/encoder.h"
#include "pw_status/status.h"

namespace pw::rpc::internal::pwpb {
enum class PacketType : uint32_t {
  REQUEST = 0, RESPONSE = 1, CLIENT_STREAM = 2, CLIENT_ERROR = 4,
  SERVER_ERROR = 5, SERVER_STREAM = 7, CLIENT_REQUEST_COMPLETION = 8,
};
namespace RpcPacket {
enum class Fields : uint32_t {
  kType = 1, kChannelId = 2, kServiceId = 3, kMethodId = 4,
  kPayload = 5, kStatus = 6, kCallId = 7,
};
class MemoryEncoder : public protobuf::MemoryEncoder {
 public:
  explicit MemoryEncoder(ByteSpan b) : protobuf::MemoryEncoder(b) {}
  Status WriteType(PacketType v) { return WriteUint32(1, static_cast<uint32_t>(v)); }
  Status WriteChannelId(uint32_t v) { return WriteUint32(2, v); }
  Status WriteServiceId(uint32_t v) { return WriteFixed32(3, v); }
  Status WriteMethodId(uint32_t v) { return WriteFixed32(4, v); }
  Status WritePayload(ConstByteSpan v) { return WriteBytes(5, v); }
  Status WriteStatus(uint32_t v) { return WriteUint32(6, v); }
  Status WriteCallId(uint32_t v) { return WriteUint32(7, v); }
};
}  // namespace RpcPacket
constexpr const char* PacketTypeToString(PacketType t) {
  switch (t) {
    case PacketType::REQUEST: return "REQUEST";
    case PacketType::RESPONSE: return "RESPONSE";
    case PacketType::CLIENT_STREAM: return "CLIENT_STREAM";
    case PacketType::CLIENT_ERROR: return "CLIENT_ERROR";
    case PacketType::SERVER_ERROR: return "SERVER_ERROR";
    case PacketType::SERVER_STREAM: return "SERVER_STREAM";
    case PacketType::CLIENT_REQUEST_COMPLETION: return "CLIENT_REQUEST_COMPLETION";
  }
  return "UNKNOWN";
}
}  // namespace pw::rpc::internal::pwpb
