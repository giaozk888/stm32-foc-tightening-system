/* A/B shared: genuine upstream TransferService + TransferThread, CAN read only. */
#include "rpc_readonly_wire.h"
#include "pw_can_rpc.h"
#include "official_log_transfer.h"
#include "transfer_can_wire.h"
#include "transfer_chunk_validation.h"
#include "pw_rpc/internal/packet.h"
#include "pw_transfer/transfer.h"
#include "pw_transfer/internal/chunk.h"
#include "pw_sync/mutex.h"
#include <mutex>
#include <atomic>
#if !defined(PW_TRANSFER_HOST)
#include "pw_thread/thread.h"
#include "pw_thread_freertos/context.h"
#include "pw_thread_freertos/options.h"
#endif
#if defined(CAN_MOTOR_CONTROL_SERVICE)
#include "pw_motor_control_rpc.inc"
#endif
namespace can_readonly_rpc {
constexpr uint32_t transferServiceId = pw::rpc::internal::Hash("pw.transfer.Transfer");
constexpr uint32_t transferReadId = pw::rpc::internal::Hash("Read");
std::array<std::byte, 96> chunkBuffer{};
std::array<std::byte, CAN_RPC_MAX_PACKET> encodeBuffer{};
pw::transfer::Thread<0, 1> transferThread(chunkBuffer, encodeBuffer);
official_log_transfer::HistoryHandler history;
std::atomic<uint32_t> streamEpoch{0};
class Output final : public pw::rpc::ChannelOutput {
 public:
  Output() : ChannelOutput("can-readonly-binary") {}
  size_t MaximumTransmissionUnit() override { return CAN_RPC_MAX_PACKET; }
  pw::Status Send(pw::ConstByteSpan bytes) override {
    rpc_readonly::Packet packet;
    if (!rpc_readonly::decode(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size(), packet))
      return pw::Status::InvalidArgument();
    const bool stream = packet.service_id == transferServiceId && packet.method_id == transferReadId;
    const int sent = stream ? PW_CanRpc_SubmitStreamResponse(transfer_can::packetId(sequence.fetch_add(1)),
        streamEpoch.load(), reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size()) :
        PW_CanRpc_SubmitResponse(transaction, reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
    if (sent && stream) {
      auto chunk = pw::transfer::internal::Chunk::Parse(pw::ConstByteSpan(
          reinterpret_cast<const std::byte*>(packet.payload), packet.payload_size));
      if (chunk.ok() && chunk->type() == pw::transfer::internal::Chunk::Type::kCompletionAck) {
        std::lock_guard<pw::sync::Mutex> guard(ackMutex);
        // The pinned engine retires a server context when it queues this ACK.
        // Keep just this canonical packet for a lost-ACK retry, not log data.
        ackPacket.length = static_cast<uint16_t>(bytes.size());
        std::memcpy(ackPacket.bytes, bytes.data(), bytes.size());
        ackCall = packet.call_id; ackSession = chunk->session_id();
        ackEpoch = streamEpoch.load(); ackTime = protocolTime.load();
      }
    }
    return sent ? pw::OkStatus() : pw::Status::ResourceExhausted();
  }
  bool ReplayCompletion(const rpc_readonly::Packet& packet) {
    if (packet.type != 2) return false;
    auto chunk = pw::transfer::internal::Chunk::Parse(pw::ConstByteSpan(
        reinterpret_cast<const std::byte*>(packet.payload), packet.payload_size));
    if (!chunk.ok() || chunk->type() != pw::transfer::internal::Chunk::Type::kCompletion) return false;
    std::lock_guard<pw::sync::Mutex> guard(ackMutex);
    if (!ackPacket.length || ackCall != packet.call_id || ackSession != chunk->session_id() ||
        ackEpoch != PW_CanRpc_LinkEpoch() || uint32_t(protocolTime.load() - ackTime) >= 60000U) return false;
    return PW_CanRpc_SubmitStreamResponse(transfer_can::packetId(sequence.fetch_add(1)), ackEpoch,
        ackPacket.bytes, ackPacket.length) != 0;
  }
  void ClearAck() { std::lock_guard<pw::sync::Mutex> guard(ackMutex); ackPacket.length = 0; }
  uint16_t transaction = 0;
  std::atomic<uint32_t> sequence{1};
  std::atomic<uint32_t> protocolTime{0};
 private:
  pw::sync::Mutex ackMutex;
  CanRpcPacket ackPacket{};
  uint32_t ackCall = 0, ackSession = 0, ackEpoch = 0, ackTime = 0;
};
template <typename Impl>
class ServiceBase : public pw::rpc::Service {
 public:
  ServiceBase() : Service(rpc_readonly::service, methods) {}
 private:
  static constexpr std::array<pw::rpc::internal::RawMethodUnion, 4> methods = {
      pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Ping>(rpc_readonly::ping),
      pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Status>(rpc_readonly::status),
      pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Params>(rpc_readonly::params),
      pw::rpc::internal::RawMethod::AsynchronousUnary<&Impl::Diagnostics>(rpc_readonly::diagnostics),
  };
};
class Service final : public ServiceBase<Service> {
 public:
  void Ping(pw::ConstByteSpan request, pw::rpc::RawUnaryResponder& responder) {
    static constexpr char alive[] = "CAN_RPC_ALIVE";
    responder.Finish(request.empty() ? pw::ConstByteSpan(reinterpret_cast<const std::byte*>(alive), sizeof(alive)-1) : request,
                     pw::OkStatus()).IgnoreError();
  }
  void Status(pw::ConstByteSpan, pw::rpc::RawUnaryResponder& r) { Snapshot(rpc_readonly::status, r); }
  void Params(pw::ConstByteSpan, pw::rpc::RawUnaryResponder& r) { Snapshot(rpc_readonly::params, r); }
  void Diagnostics(pw::ConstByteSpan, pw::rpc::RawUnaryResponder& r) { Snapshot(rpc_readonly::diagnostics, r); }
 private:
  void Snapshot(uint32_t method, pw::rpc::RawUnaryResponder& responder) {
    std::array<uint8_t, RPC_READONLY_PAYLOAD_MAX> bytes{};
    const uint32_t kind = method == rpc_readonly::status ? RPC_READONLY_SNAPSHOT_STATUS :
        method == rpc_readonly::params ? RPC_READONLY_SNAPSHOT_PARAMS : RPC_READONLY_SNAPSHOT_DIAGNOSTICS;
    const size_t size = PW_Rpc_ReadOnlySnapshot(kind, bytes.data(), bytes.size());
    responder.Finish(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(bytes.data()), size),
        size ? pw::OkStatus() : pw::Status::Unavailable()).IgnoreError();
  }
};
Output output;
pw::rpc::Channel channels[] = {pw::rpc::Channel::Create<rpc_readonly::channel>(&output)};
pw::rpc::Server server(channels);
Service service;
pw::transfer::TransferService transferService(transferThread, official_log_transfer::window,
#if defined(PW_TRANSFER_TEST_TIMEOUT_MS)
    std::chrono::milliseconds(PW_TRANSFER_TEST_TIMEOUT_MS * 4), 0, 2, 12);
#else
    std::chrono::seconds(30), 0, 2, 12);
#endif
bool initialized = false;
bool handlerRegistered = false;
bool threadStarted = false;
#if !defined(PW_TRANSFER_HOST)
pw::thread::freertos::StaticContextWithStack<1536> transferContext;
#endif
bool transferAllowed(const rpc_readonly::Packet& p) {
  if (p.channel_id != rpc_readonly::channel || p.service_id != transferServiceId ||
      p.method_id != transferReadId || !p.call_id || p.status || p.payload_size > chunkBuffer.size()) return false;
  if (p.type == 0 || p.type == 8) return p.payload_size == 0;
  if (p.type != 2 || !p.payload_size) return false;
  if (!transfer_can::validV2Chunk(pw::ConstByteSpan(
      reinterpret_cast<const std::byte*>(p.payload), p.payload_size))) return false;
  auto parsed = pw::transfer::internal::Chunk::Parse(pw::ConstByteSpan(
      reinterpret_cast<const std::byte*>(p.payload), p.payload_size));
  if (!parsed.ok() || !parsed->payload().empty()) return false;
  using Chunk = pw::transfer::internal::Chunk;
  if (parsed->type() == Chunk::Type::kStart)
    return parsed->protocol_version() == pw::transfer::ProtocolVersion::kVersionTwo &&
        parsed->resource_id() == official_log_transfer::resource &&
        parsed->desired_session_id().value_or(0) && parsed->initial_offset() == 0 &&
        parsed->window_end_offset() <= official_log_transfer::window;
  if (!parsed->session_id() || parsed->resource_id().has_value() || parsed->offset() > official_log_transfer::capacity)
    return false;
  switch (parsed->type()) {
    case Chunk::Type::kParametersContinue:
    case Chunk::Type::kParametersRetransmit:
    case Chunk::Type::kStartAckConfirmation:
      return parsed->window_end_offset() >= parsed->offset() &&
          parsed->window_end_offset() - parsed->offset() <= official_log_transfer::window;
    case Chunk::Type::kCompletion:
    case Chunk::Type::kCompletionAck: return true;
    default: return false;
  }
}
}
extern "C" int PW_Rpc_CanInit(void) {
  using namespace can_readonly_rpc;
  if (initialized) return 1;
#if !defined(PW_TRANSFER_HOST)
  if (!threadStarted) {
    auto options = pw::thread::freertos::Options().set_name("PwTransfer").set_priority(1U)
        .set_static_context(transferContext);
    pw::Thread(options, transferThread).detach();
    threadStarted = true;
  }
#endif
  if (!transferService.RegisterHandler(history)) return 0;
  handlerRegistered = true;
  transferService.set_max_chunk_size_bytes(official_log_transfer::block);
  server.RegisterService(service, transferService);
#if defined(CAN_MOTOR_CONTROL_SERVICE)
  server.RegisterService(motor_control_rpc::service);
#endif
  streamEpoch.store(PW_CanRpc_LinkEpoch()); initialized = true; return 1;
}
extern "C" void PW_Rpc_CanTick(uint32_t now) {
  using namespace can_readonly_rpc;
  history.setTime(now);
  output.protocolTime.store(now);
  const auto epoch = PW_CanRpc_LinkEpoch();
  if (!initialized) return;
  if (handlerRegistered && (epoch != streamEpoch.load() || history.expired())) {
    if (!transferService.UnregisterHandler(history)) return;
    handlerRegistered = false;
    output.ClearAck();
    server.CloseChannel(rpc_readonly::channel).IgnoreError();
    server.OpenChannel(rpc_readonly::channel, output).IgnoreError();
  }
  if (!handlerRegistered && transferService.RegisterHandler(history)) {
    handlerRegistered = true; streamEpoch.store(epoch);
  }
}
extern "C" int PW_Rpc_CanProcess(uint16_t transaction, const uint8_t* data, size_t size) {
  using namespace can_readonly_rpc;
  rpc_readonly::Packet packet;
  if (!initialized || !handlerRegistered || streamEpoch.load() != PW_CanRpc_LinkEpoch() ||
      !transaction || !rpc_readonly::decode(data, size, packet) ||
      !(rpc_readonly::requestAllowed(packet) || transferAllowed(packet)
#if defined(CAN_MOTOR_CONTROL_SERVICE)
        || motor_rpc::requestAllowed(packet)
#endif
      )) return 0;
  const bool stream = transferAllowed(packet);
  if (stream != transfer_can::isStream(transaction)) return 0;
  if (stream && packet.type == 0) output.ClearAck();
  if (stream && output.ReplayCompletion(packet)) return 1;
  output.transaction = transaction;
  auto result = server.ProcessPacket(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(data), size));
  output.transaction = 0; return result.ok();
}
#if defined(PW_TRANSFER_HOST)
extern "C" void PW_Rpc_CanTransferRun(void) { can_readonly_rpc::transferThread.Start(); }
extern "C" void PW_Rpc_CanTransferTimeout(uint32_t session) {
  can_readonly_rpc::transferThread.SimulateServerTimeout(session);
  can_readonly_rpc::transferThread.WaitUntilEventIsProcessed();
}
extern "C" void PW_Rpc_CanTransferStop(void) {
  using namespace can_readonly_rpc;
  if (handlerRegistered) transferService.UnregisterHandler(history);
  transferThread.Terminate();
}
#endif
