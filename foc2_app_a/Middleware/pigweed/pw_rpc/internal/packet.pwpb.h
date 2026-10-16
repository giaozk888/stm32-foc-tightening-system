#pragma once

// Minimal checked-in pwpb binding for pw_rpc/internal/packet.proto.
// The normal Pigweed build generates this file with protoc.  This embedded
// CMake project intentionally does not require a host-side protoc install, so
// only the enum and encoder surface used by pw_rpc are provided here.

#include <cstdint>

#include "pw_bytes/span.h"
#include "pw_protobuf/encoder.h"
#include "pw_status/status.h"

namespace pw::rpc::internal::pwpb {

enum class PacketType : uint32_t {
  REQUEST = 0,
  RESPONSE = 1,
  CLIENT_STREAM = 2,
  CLIENT_ERROR = 4,
  SERVER_ERROR = 5,
  SERVER_STREAM = 7,
  CLIENT_REQUEST_COMPLETION = 8,
};

namespace RpcPacket {
  enum class Fields : uint32_t {
    kType = 1,
    kChannelId = 2,
    kServiceId = 3,
    kMethodId = 4,
    kPayload = 5,
    kStatus = 6,
    kCallId = 7,
  };

  class MemoryEncoder : public protobuf::MemoryEncoder {
   public:
    explicit MemoryEncoder(ByteSpan buffer) : protobuf::MemoryEncoder(buffer) {}

    Status WriteType(PacketType value) {
      return WriteUint32(static_cast<uint32_t>(Fields::kType),
                         static_cast<uint32_t>(value));
    }
    Status WriteChannelId(uint32_t value) {
      return WriteUint32(static_cast<uint32_t>(Fields::kChannelId), value);
    }
    Status WriteServiceId(uint32_t value) {
      return WriteFixed32(static_cast<uint32_t>(Fields::kServiceId), value);
    }
    Status WriteMethodId(uint32_t value) {
      return WriteFixed32(static_cast<uint32_t>(Fields::kMethodId), value);
    }
    Status WritePayload(ConstByteSpan value) {
      return WriteBytes(static_cast<uint32_t>(Fields::kPayload), value);
    }
    Status WriteStatus(uint32_t value) {
      return WriteUint32(static_cast<uint32_t>(Fields::kStatus), value);
    }
    Status WriteCallId(uint32_t value) {
      return WriteUint32(static_cast<uint32_t>(Fields::kCallId), value);
    }
  };
}  // namespace RpcPacket

constexpr const char *PacketTypeToString(PacketType type) {
  switch (type) {
    case PacketType::REQUEST: return "REQUEST";
    case PacketType::RESPONSE: return "RESPONSE";
    case PacketType::CLIENT_STREAM: return "CLIENT_STREAM";
    case PacketType::CLIENT_ERROR: return "CLIENT_ERROR";
    case PacketType::SERVER_ERROR: return "SERVER_ERROR";
    case PacketType::SERVER_STREAM: return "SERVER_STREAM";
    case PacketType::CLIENT_REQUEST_COMPLETION:
      return "CLIENT_REQUEST_COMPLETION";
  }
  return "UNKNOWN";
}

}  // namespace pw::rpc::internal::pwpb
