#include "pw_rpc_service.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "pw_bytes/span.h"
#include "pw_rpc/channel.h"
#include "pw_rpc/internal/hash.h"
#include "pw_rpc/raw/internal/method.h"
#include "pw_rpc/raw/internal/method_union.h"
#include "pw_rpc/raw/server_reader_writer.h"
#include "pw_rpc/server.h"
#include "pw_rpc/service.h"
#include "pw_result/result.h"
#include "pw_status/status.h"
#include "pw_transfer/internal/chunk.h"
#if defined(CAN_RPC_READ_ONLY)
#include "pw_rpc_can_readonly.inc"
#endif

extern "C" uint8_t PW_Rpc_ProtocolSend(const char *line);

namespace {

constexpr uint32_t kChannelId = 1;
constexpr uint32_t kServiceId = pw::rpc::internal::Hash("foc.Control");
constexpr uint32_t kPingMethodId = pw::rpc::internal::Hash("Ping");
constexpr uint32_t kTransferServiceId = pw::rpc::internal::Hash("foc.Transfer");
constexpr uint32_t kTransferMethodId = pw::rpc::internal::Hash("Exchange");
constexpr uint32_t kOfficialTransferServiceId =
    pw::rpc::internal::Hash("pw.transfer.Transfer");
constexpr uint32_t kOfficialWriteMethodId = pw::rpc::internal::Hash("Write");
constexpr size_t kMaxPacketBytes = 96;
constexpr uint32_t kTransferResourceId = 1;
constexpr uint32_t kTransferFlashResourceId = 2;
constexpr size_t kTransferCapacity = 512;
constexpr size_t kTransferChunkSize = 32;

uint32_t g_request_id = 0;
uint32_t g_rx_packets = 0;
uint32_t g_tx_packets = 0;
uint32_t g_errors = 0;
bool g_initialized = false;
std::array<std::byte, kTransferCapacity> g_transfer_data{};
uint32_t g_transfer_session = 0;
uint32_t g_transfer_offset = 0;
uint32_t g_transfer_crc32 = 0;
uint32_t g_transfer_chunks = 0;
uint32_t g_transfer_retransmits = 0;
bool g_transfer_active = false;
uint32_t g_transfer_resource = 0;
uint32_t g_transfer_capacity = kTransferCapacity;

extern "C" uint8_t PW_TransferFlash_IsActive(void);
extern "C" uint32_t PW_TransferFlash_ExpectedOffset(void);
extern "C" uint32_t PW_TransferFlash_ImageSize(void);
extern "C" uint8_t PW_TransferFlash_Write(uint32_t offset,
                                           const uint8_t* data,
                                           uint32_t length);

uint32_t TransferCrc32(pw::ConstByteSpan data) {
  uint32_t crc = 0xffffffffu;
  for (std::byte value : data) {
    crc ^= static_cast<uint8_t>(value);
    for (unsigned bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ ((crc & 1u) ? 0xedb88320u : 0u);
    }
  }
  return crc ^ 0xffffffffu;
}

class AsciiHexOutput final : public pw::rpc::ChannelOutput {
 public:
  constexpr AsciiHexOutput() : ChannelOutput("router-ascii-hex") {}

  size_t MaximumTransmissionUnit() override { return kMaxPacketBytes; }

  pw::Status Send(pw::span<const std::byte> packet) override {
    if (packet.size() > kMaxPacketBytes) {
      ++g_errors;
      return pw::Status::ResourceExhausted();
    }

    char line[32 + (kMaxPacketBytes * 2)];
    int written = std::snprintf(line,
                                sizeof(line),
                                "%lu OK RPC ",
                                static_cast<unsigned long>(g_request_id));
    if (written < 0) {
      ++g_errors;
      return pw::Status::Internal();
    }

    static constexpr char kHex[] = "0123456789ABCDEF";
    size_t pos = static_cast<size_t>(written);
    for (std::byte value : packet) {
      const uint8_t byte = static_cast<uint8_t>(value);
      line[pos++] = kHex[byte >> 4];
      line[pos++] = kHex[byte & 0x0f];
    }
    line[pos++] = '\r';
    line[pos++] = '\n';
    line[pos] = '\0';

    if (PW_Rpc_ProtocolSend(line) == 0U) {
      ++g_errors;
      return pw::Status::Unavailable();
    }
    ++g_tx_packets;
    return pw::OkStatus();
  }
};

template <typename Impl>
class ControlServiceBase : public pw::rpc::Service {
 public:
  ControlServiceBase() : Service(kServiceId, kMethods) {}

 private:
  static constexpr std::array<pw::rpc::internal::RawMethodUnion, 1> kMethods = {
      pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Ping>(
          kPingMethodId),
  };
};

class ControlService final : public ControlServiceBase<ControlService> {
 public:
  void Ping(pw::ConstByteSpan request,
            pw::rpc::RawUnaryResponder &responder) {
    // Echo the request when present; an empty request returns an unmistakable
    // bring-up marker. This exercises dispatch, call correlation and response
    // encoding without touching the FOC control path.
    static constexpr std::array<std::byte, 12> kAlive = {
        std::byte{'P'}, std::byte{'W'}, std::byte{'_'}, std::byte{'R'},
        std::byte{'P'}, std::byte{'C'}, std::byte{'_'}, std::byte{'A'},
        std::byte{'L'}, std::byte{'I'}, std::byte{'V'}, std::byte{'E'},
    };
    const pw::ConstByteSpan response = request.empty()
                                          ? pw::ConstByteSpan(kAlive)
                                          : request;
    if (!responder.Finish(response, pw::OkStatus()).ok()) {
      ++g_errors;
    }
  }
};

template <typename Impl>
class TransferServiceBase : public pw::rpc::Service {
 public:
  TransferServiceBase() : Service(kTransferServiceId, kMethods) {}
 private:
  static constexpr std::array<pw::rpc::internal::RawMethodUnion, 1> kMethods = {
      pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Exchange>(
          kTransferMethodId),
  };
};

class TransferService final : public TransferServiceBase<TransferService> {
 public:
  static pw::Result<pw::ConstByteSpan> ProcessChunk(
      pw::ConstByteSpan request,
      std::array<std::byte, 64>& encoded) {
    using pw::transfer::ProtocolVersion;
    using TransferChunk = pw::transfer::internal::Chunk;
    auto parsed = TransferChunk::Parse(request);
    if (!parsed.ok()) {
      ++g_errors;
      return pw::Status::DataLoss();
    }

    const TransferChunk& input = parsed.value();
    TransferChunk output(ProtocolVersion::kVersionTwo,
                         TransferChunk::Type::kParametersContinue);
    const uint32_t session = input.session_id();

    if (input.type() == TransferChunk::Type::kStart) {
      const uint32_t resource = input.resource_id().value_or(0);
      const bool ram_ok = resource == kTransferResourceId &&
                          input.initial_offset() <= kTransferCapacity;
      const bool flash_ok = resource == kTransferFlashResourceId &&
                            PW_TransferFlash_IsActive() != 0U &&
                            input.initial_offset() ==
                                PW_TransferFlash_ExpectedOffset();
      if (session == 0 || (!ram_ok && !flash_ok)) {
        output = TransferChunk::Final(ProtocolVersion::kVersionTwo,
                                      session,
                                      pw::Status::InvalidArgument());
      } else {
        g_transfer_session = session;
        g_transfer_resource = resource;
        g_transfer_capacity = ram_ok ? kTransferCapacity
                                     : PW_TransferFlash_ImageSize();
        g_transfer_offset = input.initial_offset();
        g_transfer_chunks = 0;
        g_transfer_retransmits = 0;
        g_transfer_crc32 = 0;
        g_transfer_active = true;
        output = TransferChunk(ProtocolVersion::kVersionTwo,
                               TransferChunk::Type::kStartAck)
                     .set_session_id(session)
                     .set_resource_id(resource)
                     .set_protocol_version(ProtocolVersion::kVersionTwo)
                     .set_initial_offset(g_transfer_offset);
      }
    } else if (!g_transfer_active || session != g_transfer_session) {
      output = TransferChunk::Final(ProtocolVersion::kVersionTwo,
                                    session,
                                    pw::Status::FailedPrecondition());
    } else if (input.type() == TransferChunk::Type::kStartAckConfirmation) {
      output.set_session_id(session)
          .set_offset(g_transfer_offset)
          .set_window_end_offset(g_transfer_offset + kTransferChunkSize)
          .set_max_chunk_size_bytes(kTransferChunkSize);
    } else if (input.type() == TransferChunk::Type::kData) {
      if (input.offset() != g_transfer_offset ||
          input.payload().size() > kTransferChunkSize ||
          input.payload().size() > g_transfer_capacity - g_transfer_offset) {
        ++g_transfer_retransmits;
        output = TransferChunk(ProtocolVersion::kVersionTwo,
                               TransferChunk::Type::kParametersRetransmit)
                     .set_session_id(session)
                     .set_offset(g_transfer_offset)
                     .set_window_end_offset(g_transfer_offset + kTransferChunkSize)
                     .set_max_chunk_size_bytes(kTransferChunkSize);
      } else {
        bool write_ok = true;
        if (g_transfer_resource == kTransferFlashResourceId) {
          write_ok = PW_TransferFlash_Write(
                         g_transfer_offset,
                         reinterpret_cast<const uint8_t*>(input.payload().data()),
                         input.payload().size()) != 0U;
        } else {
          std::memcpy(g_transfer_data.data() + g_transfer_offset,
                      input.payload().data(),
                      input.payload().size());
        }

        if (!write_ok) {
          ++g_transfer_retransmits;
          if (g_transfer_resource == kTransferFlashResourceId) {
            g_transfer_offset = PW_TransferFlash_ExpectedOffset();
          }
          output = TransferChunk(ProtocolVersion::kVersionTwo,
                                 TransferChunk::Type::kParametersRetransmit)
                       .set_session_id(session)
                       .set_offset(g_transfer_offset)
                       .set_window_end_offset(g_transfer_offset + kTransferChunkSize)
                       .set_max_chunk_size_bytes(kTransferChunkSize);
        } else {
          g_transfer_offset += input.payload().size();
          ++g_transfer_chunks;

          if (input.remaining_bytes().has_value() &&
              input.remaining_bytes().value() == 0) {
            if (g_transfer_resource == kTransferResourceId) {
              g_transfer_crc32 = TransferCrc32(
                  pw::ConstByteSpan(g_transfer_data.data(), g_transfer_offset));
            }
            g_transfer_active = false;
            output = TransferChunk::Final(ProtocolVersion::kVersionTwo,
                                          session,
                                          pw::OkStatus());
          } else {
            output.set_session_id(session)
                .set_offset(g_transfer_offset)
                .set_window_end_offset(g_transfer_offset + kTransferChunkSize)
                .set_max_chunk_size_bytes(kTransferChunkSize);
          }
        }
      }
    } else {
      output = TransferChunk::Final(ProtocolVersion::kVersionTwo,
                                    session,
                                    pw::Status::InvalidArgument());
    }

    auto result = output.Encode(encoded);
    if (!result.ok()) {
      ++g_errors;
      return result.status();
    }
    return result.value();
  }

  void Exchange(pw::ConstByteSpan request,
                pw::rpc::RawUnaryResponder& responder) {
    std::array<std::byte, 64> encoded{};
    auto result = ProcessChunk(request, encoded);
    if (!result.ok()) {
      static_cast<void>(responder.Finish({}, result.status()));
      return;
    }
    if (!responder.Finish(result.value(), pw::OkStatus()).ok()) {
      ++g_errors;
    }
  }
};

// Complete official firmware Write lives in uart_firmware_transfer.cc.
// Historical unary Exchange remains available for recovery compatibility.

AsciiHexOutput g_output;
pw::rpc::Channel g_channels[] = {
    pw::rpc::Channel::Create<kChannelId>(&g_output),
};
pw::rpc::Server g_server(g_channels);
ControlService g_service;
TransferService g_transfer_service;

int HexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

void SendInfo(uint32_t request_id) {
  char line[192];
  std::snprintf(line,
                sizeof(line),
                "%lu OK RPC READY=%u CH=%lu SERVICE=0x%08lX METHOD=0x%08lX "
                "RX=%lu TX=%lu ERR=%lu TRANSPORT=ASCII_HEX\r\n",
                static_cast<unsigned long>(request_id),
                g_initialized ? 1U : 0U,
                static_cast<unsigned long>(kChannelId),
                static_cast<unsigned long>(kServiceId),
                static_cast<unsigned long>(kPingMethodId),
                static_cast<unsigned long>(g_rx_packets),
                static_cast<unsigned long>(g_tx_packets),
                static_cast<unsigned long>(g_errors));
  PW_Rpc_ProtocolSend(line);
}

void SendError(uint32_t request_id, const char *reason) {
  char line[128];
  ++g_errors;
  std::snprintf(line,
                sizeof(line),
                "%lu ERR 103 RPC_%s\r\n",
                static_cast<unsigned long>(request_id),
                reason);
  PW_Rpc_ProtocolSend(line);
}

}  // namespace

extern "C" void PW_Rpc_Init(void) {
  if (!g_initialized) {
    g_server.RegisterService(
        g_service, g_transfer_service);
    g_initialized = true;
  }
}

extern "C" void PW_Transfer_HandleCommand(uint32_t request_id,
                                            const char* args) {
  if (args == nullptr) { SendError(request_id, "XFER_MISSING_ARGUMENT"); return; }
  while (*args == ' ' || *args == '\t') ++args;
  if (std::strcmp(args, "RESET") == 0) {
    g_transfer_active = false;
    g_transfer_session = 0;
    g_transfer_resource = 0;
    g_transfer_capacity = kTransferCapacity;
    g_transfer_offset = 0;
    g_transfer_crc32 = 0;
    g_transfer_chunks = 0;
    g_transfer_retransmits = 0;
  } else if (std::strcmp(args, "STATUS") != 0 && std::strcmp(args, "INFO") != 0) {
    SendError(request_id, "XFER_BAD_COMMAND");
    return;
  }
  char line[320];
  std::snprintf(line, sizeof(line),
      "%lu OK XFER READY=%u RESOURCE=%lu CAP=%lu ACTIVE=%u SESSION=%lu "
      "OFFSET=%lu CHUNKS=%lu RETRANSMIT=%lu CRC32=0x%08lX "
      "SERVICE=0x%08lX METHOD=0x%08lX PROTO=2 FLASH=%u "
      "OFFICIAL_SERVICE=0x%08lX WRITE=0x%08lX STREAM=0\r\n",
      static_cast<unsigned long>(request_id), g_initialized ? 1U : 0U,
      static_cast<unsigned long>(g_transfer_resource),
      static_cast<unsigned long>(g_transfer_capacity), g_transfer_active ? 1U : 0U,
      static_cast<unsigned long>(g_transfer_session),
      static_cast<unsigned long>(g_transfer_offset),
      static_cast<unsigned long>(g_transfer_chunks),
      static_cast<unsigned long>(g_transfer_retransmits),
      static_cast<unsigned long>(g_transfer_crc32),
      static_cast<unsigned long>(kTransferServiceId),
      static_cast<unsigned long>(kTransferMethodId),
      PW_TransferFlash_IsActive() != 0U ? 1U : 0U,
      static_cast<unsigned long>(kOfficialTransferServiceId),
      static_cast<unsigned long>(kOfficialWriteMethodId));
  PW_Rpc_ProtocolSend(line);
}

extern "C" void PW_Rpc_HandleCommand(uint32_t request_id, const char *args) {
  if (args == nullptr) {
    SendError(request_id, "MISSING_ARGUMENT");
    return;
  }
  while (*args == ' ' || *args == '\t') ++args;

  if (std::strcmp(args, "INFO") == 0 || std::strcmp(args, "STATUS") == 0) {
    SendInfo(request_id);
    return;
  }
  if (std::strncmp(args, "CALL ", 5) == 0) args += 5;

  const size_t chars = std::strlen(args);
  if (chars == 0 || (chars & 1U) != 0 || chars > kMaxPacketBytes * 2U) {
    SendError(request_id, "BAD_HEX_LENGTH");
    return;
  }

  std::array<std::byte, kMaxPacketBytes> packet{};
  const size_t bytes = chars / 2U;
  for (size_t i = 0; i < bytes; ++i) {
    const int high = HexNibble(args[i * 2U]);
    const int low = HexNibble(args[i * 2U + 1U]);
    if (high < 0 || low < 0) {
      SendError(request_id, "BAD_HEX");
      return;
    }
    packet[i] = static_cast<std::byte>((high << 4) | low);
  }

  if (!g_initialized) PW_Rpc_Init();
  g_request_id = request_id;
  ++g_rx_packets;
  const uint32_t tx_before = g_tx_packets;
  const pw::Status status =
      g_server.ProcessPacket(pw::ConstByteSpan(packet.data(), bytes));
  if (!status.ok()) {
    SendError(request_id, "PACKET_REJECTED");
  } else if (g_tx_packets == tx_before) {
    char line[64];
    std::snprintf(line,
                  sizeof(line),
                  "%lu OK RPC ACCEPTED\r\n",
                  static_cast<unsigned long>(request_id));
    PW_Rpc_ProtocolSend(line);
  }
}
