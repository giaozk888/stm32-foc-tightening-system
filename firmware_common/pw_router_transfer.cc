#include "pw_router_transfer.h"
#include "official_log_transfer.h"
#include "rpc_readonly_wire.h"
#include "transfer_chunk_validation.h"
#include "pw_rpc/server.h"
#include "pw_rpc/internal/hash.h"
#include "pw_sync/mutex.h"
#include "pw_stream/memory_stream.h"
#include "pw_transfer/transfer.h"
#include "pw_transfer/internal/chunk.h"
#include <atomic>
#include <mutex>
#if defined(AS5047P_SPI_DMA)
#include "as5047p_dma_stm32.h"
#endif
#if !defined(PW_TRANSFER_HOST)
#include "pw_thread/thread.h"
#include "pw_thread_freertos/context.h"
#include "pw_thread_freertos/options.h"
#endif

namespace router_transfer {
constexpr uint32_t serviceId = pw::rpc::internal::Hash("pw.transfer.Transfer");
constexpr uint32_t readId = pw::rpc::internal::Hash("Read");
constexpr size_t packetCapacity = 128;
using Chunk = pw::transfer::internal::Chunk;
std::array<std::byte, 96> chunkBuffer{};
std::array<std::byte, packetCapacity> encodeBuffer{};
pw::transfer::Thread<0, 1> transferThread(chunkBuffer, encodeBuffer);
official_log_transfer::HistoryHandler history;
// A frozen, self-checking sample file; CRC is software packet protection, NOT
// a sensor SPI CRC. No SPI transaction or periodic-sampling start is requested.
class EncoderHandler final : public pw::transfer::ReadOnlyHandler {
  public:
    EncoderHandler() : ReadOnlyHandler(4, reader), reader(pw::ConstByteSpan(bytes)) {}
    pw::Status PrepareRead() override {
#if defined(AS5047P_SPI_DMA)
        AsDmaSample sample{};
        uint32_t capturedNow = 0;
        if (!AS5047P_DmaSnapshot(&sample, &capturedNow))
            return pw::Status::Unavailable();
        auto put = [&](size_t offset, uint32_t value) {
            rpc_readonly::put32(reinterpret_cast<uint8_t *>(bytes.data()) + offset, value);
        };
        put(0, 0x31434E45U); // "ENC1" little endian
        put(4, 1);
        put(8, sample.sequence);
        put(12, sample.sample_us);
        put(16, sample.completed_us);
        put(20, capturedNow);
        put(24, uint32_t(sample.status));
        put(28, uint32_t(sample.raw) | (uint32_t(sample.response) << 16));
        put(32, uint32_t(sample.errfl) | (uint32_t(sample.errfl_valid) << 16) |
                    (uint32_t(sample.recovered) << 24));
        put(36, rn_transfer_crc32(reinterpret_cast<const uint8_t *>(bytes.data()), 36));
        return reader.Seek(0);
#else
        return pw::Status::Unimplemented();
#endif
    }
    pw::Status PrepareRead(uint32_t) override {
        return pw::Status::Unimplemented();
    }
    size_t ResourceSize() const override {
        return bytes.size();
    }

  private:
    std::array<std::byte, 40> bytes{};
    pw::stream::MemoryReader reader;
};
EncoderHandler encoder;
rn_transfer_receiver_t receiver{};

struct Owner {
    uint16_t peer = 0;
    RouterPort_t port = ROUTER_PORT_LOCAL;
    uint32_t epoch = 0, call = 0;
};
class Output final : public pw::rpc::ChannelOutput {
  public:
    Output() : ChannelOutput("router-transfer-fragmented") {}
    size_t MaximumTransmissionUnit() override {
        return packetCapacity;
    }
    bool sendPacket(const Owner &owner, pw::ConstByteSpan bytes) {
        if (!owner.peer || Router_PortEpoch(owner.port) != owner.epoch)
            return false;
        uint32_t id = sequence.fetch_add(1);
        if (!id)
            id = sequence.fetch_add(1);
        char text[225];
        for (size_t offset = 0; offset < bytes.size(); offset += RN_TRANSFER_FRAGMENT) {
            if (!rn_transfer_format(id, reinterpret_cast<const uint8_t *>(bytes.data()),
                                    bytes.size(), offset, text, sizeof(text)) ||
                Router_PortEpoch(owner.port) != owner.epoch ||
                !Router_SendText(owner.peer, RN_TRANSFER_TYPE, text, nullptr))
                return false;
        }
        return true;
    }
    pw::Status Send(pw::ConstByteSpan bytes) override {
        rpc_readonly::Packet p;
        if (bytes.size() > packetCapacity ||
            !rpc_readonly::decode(reinterpret_cast<const uint8_t *>(bytes.data()), bytes.size(),
                                  p) ||
            p.service_id != serviceId || p.method_id != readId)
            return pw::Status::InvalidArgument();
        Owner destination;
        {
            std::lock_guard<pw::sync::Mutex> lock(mutex);
            destination = owner;
            if (p.call_id != owner.call || p.channel_id != RN_TRANSFER_CHANNEL_BASE + owner.peer)
                return pw::Status::Unavailable();
            auto chunk = Chunk::Parse(
                p.payload_size ? pw::ConstByteSpan(reinterpret_cast<const std::byte *>(p.payload),
                                                   p.payload_size)
                               : pw::ConstByteSpan{});
            if (chunk.ok() && chunk->type() == Chunk::Type::kCompletionAck) {
                // Upstream retires its context after queuing this ACK. Retain only
                // the ACK to handle a lost final Router fragment, not history bytes.
                ackSize = bytes.size();
                std::memcpy(ack.data(), bytes.data(), bytes.size());
                ackSession = chunk->session_id();
            }
        }
        return sendPacket(destination, bytes) ? pw::OkStatus() : pw::Status::Unavailable();
    }
    void bind(Owner value) {
        std::lock_guard<pw::sync::Mutex> lock(mutex);
        owner = value;
        ackSize = 0;
    }
    bool finished() {
        std::lock_guard<pw::sync::Mutex> lock(mutex);
        return ackSize != 0;
    }
    bool replay(const rpc_readonly::Packet &p) {
        if (p.type != 2)
            return false;
        auto chunk = Chunk::Parse(
            pw::ConstByteSpan(reinterpret_cast<const std::byte *>(p.payload), p.payload_size));
        if (!chunk.ok() || chunk->type() != Chunk::Type::kCompletion)
            return false;
        std::array<std::byte, packetCapacity> copy;
        Owner destination;
        size_t size;
        {
            std::lock_guard<pw::sync::Mutex> lock(mutex);
            if (!ackSize || p.call_id != owner.call || chunk->session_id() != ackSession)
                return false;
            copy = ack;
            size = ackSize;
            destination = owner;
        }
        return sendPacket(destination, pw::ConstByteSpan(copy.data(), size));
    }

  private:
    pw::sync::Mutex mutex;
    Owner owner{};
    std::array<std::byte, packetCapacity> ack{};
    size_t ackSize = 0;
    uint32_t ackSession = 0;
    std::atomic<uint32_t> sequence{1};
};
Output output;
pw::rpc::Channel channels[1];
pw::rpc::Server server(channels);
pw::transfer::TransferService transferService(transferThread, official_log_transfer::window,
                                              std::chrono::seconds(30), 3, 2, 12);
Owner active{}; // ProtocolTask only; Output owns a mutex-protected snapshot.
uint32_t last = 0;
bool initialized = false, registered = false, retiring = false;
bool historyRegistered = false, encoderRegistered = false;
#if !defined(PW_TRANSFER_HOST)
pw::thread::freertos::StaticContextWithStack<1536> threadContext;
std::atomic<TaskHandle_t> workerHandle{nullptr};
#endif
bool allowed(const rpc_readonly::Packet &p, uint16_t src) {
    if (p.channel_id != RN_TRANSFER_CHANNEL_BASE + src || p.service_id != serviceId ||
        p.method_id != readId || !p.call_id || p.status || p.payload_size > chunkBuffer.size())
        return false;
    if (p.type == 0 || p.type == 8)
        return p.payload_size == 0;
    if (p.type != 2 || !p.payload_size ||
        !transfer_can::validV2Chunk(
            pw::ConstByteSpan(reinterpret_cast<const std::byte *>(p.payload), p.payload_size)))
        return false;
    auto chunk = Chunk::Parse(
        pw::ConstByteSpan(reinterpret_cast<const std::byte *>(p.payload), p.payload_size));
    if (!chunk.ok() || !chunk->payload().empty())
        return false;
    if (chunk->type() == Chunk::Type::kStart)
        return chunk->protocol_version() == pw::transfer::ProtocolVersion::kVersionTwo &&
               (chunk->resource_id() == official_log_transfer::resource ||
                chunk->resource_id() == 4) &&
               chunk->desired_session_id().value_or(0) && chunk->initial_offset() == 0 &&
               chunk->window_end_offset() <= official_log_transfer::window;
    if (!chunk->session_id() || chunk->resource_id().has_value() ||
        chunk->offset() > official_log_transfer::capacity)
        return false;
    switch (chunk->type()) {
    case Chunk::Type::kParametersContinue:
    case Chunk::Type::kParametersRetransmit:
    case Chunk::Type::kStartAckConfirmation:
        return chunk->window_end_offset() >= chunk->offset() &&
               chunk->window_end_offset() - chunk->offset() <= official_log_transfer::window;
    case Chunk::Type::kCompletion:
    case Chunk::Type::kCompletionAck:
        return true;
    default:
        return false;
    }
}
void retire() {
    output.bind({}); // Stop async replies before any channel can be reassigned.
    registered = false;
    if (historyRegistered) {
        if (!transferService.UnregisterHandler(history)) {
            retiring = true;
            return;
        }
        historyRegistered = false;
    }
    if (encoderRegistered) {
        if (!transferService.UnregisterHandler(encoder)) {
            retiring = true;
            return;
        }
        encoderRegistered = false;
    }
    if (active.peer)
        server.CloseChannel(RN_TRANSFER_CHANNEL_BASE + active.peer).IgnoreError();
    active = {};
    retiring = false;
}
} // namespace router_transfer
extern "C" void PW_RouterTransfer_Tick(uint32_t now) {
    using namespace router_transfer;
    history.setTime(now);
    rn_transfer_expire(&receiver, now);
    if (!initialized) {
#if !defined(PW_TRANSFER_HOST)
        auto options = pw::thread::freertos::Options()
                           .set_name("RouterTransfer")
                           .set_priority(1U)
                           .set_static_context(threadContext);
        pw::Thread(options, [] {
            workerHandle.store(xTaskGetCurrentTaskHandle(), std::memory_order_release);
            transferThread.Start();
        }).detach();
#endif
        transferService.set_max_chunk_size_bytes(official_log_transfer::block);
        server.RegisterService(transferService);
        initialized = true;
    }
    if (retiring || (active.peer && (Router_PortEpoch(active.port) != active.epoch ||
                                     uint32_t(now - last) >= 60000U || history.expired())))
        retire();
    if (!retiring) {
        if (!historyRegistered)
            historyRegistered = transferService.RegisterHandler(history);
        if (!encoderRegistered)
            encoderRegistered = transferService.RegisterHandler(encoder);
        registered = historyRegistered && encoderRegistered;
    }
}
extern "C" int PW_RouterTransfer_Process(const RouterPacket_t *frame, uint32_t now) {
    using namespace router_transfer;
    PW_RouterTransfer_Tick(now);
    if (!frame || retiring || !registered || frame->type != RN_TRANSFER_TYPE || frame->dst != 1 ||
        frame->src == 1 || frame->length > 224 ||
        std::memchr(frame->payload, '\0', sizeof(frame->payload)) !=
            frame->payload + frame->length ||
        Router_PortEpoch(frame->ingress_port) != frame->ingress_epoch)
        return 0;
    rn_transfer_view_t view;
    auto state = rn_transfer_feed(&receiver, frame->src, frame->dst, uint8_t(frame->ingress_port),
                                  frame->ingress_epoch, frame->payload, now, &view);
    if (state != RN_TRANSFER_COMPLETE)
        return state == RN_TRANSFER_PENDING;
    rpc_readonly::Packet packet;
    bool accepted = false;
    if (view.size <= packetCapacity && rpc_readonly::decode(view.data, view.size, packet) &&
        allowed(packet, frame->src)) {
        // A restarted host Client may reuse call/session 1 on the same UART.
        // Retire the old finished engine context and ACK cache before a fresh
        // REQUEST, otherwise an old final ACK could falsely finish a new file.
        if (packet.type == 0 && active.peer && output.finished()) {
            retire();
            PW_RouterTransfer_Tick(now);
        }
        const bool same = active.peer == frame->src && active.port == frame->ingress_port &&
                          active.epoch == frame->ingress_epoch && active.call == packet.call_id;
        if (packet.type == 0 && !same && (!active.peer || output.finished())) {
            if (active.peer)
                server.CloseChannel(RN_TRANSFER_CHANNEL_BASE + active.peer).IgnoreError();
            active = {frame->src, frame->ingress_port, frame->ingress_epoch, packet.call_id};
            output.bind(active);
            if (!server.OpenChannel(packet.channel_id, output).ok()) {
                output.bind({});
                active = {};
            }
        }
        if (registered && !retiring && active.peer == frame->src &&
            active.port == frame->ingress_port && active.epoch == frame->ingress_epoch &&
            active.call == packet.call_id) {
            last = now;
            accepted = output.replay(packet) ||
                       server
                           .ProcessPacket(pw::ConstByteSpan(
                               reinterpret_cast<const std::byte *>(view.data), view.size))
                           .ok();
        }
    }
    rn_transfer_release(&receiver, view.slot);
    return accepted;
}
#if defined(PW_TRANSFER_HOST)
extern "C" void PW_RouterTransfer_Run(void) {
    router_transfer::transferThread.Start();
}
extern "C" void PW_RouterTransfer_Stop(void) {
    router_transfer::output.bind({});
    if (router_transfer::registered)
        router_transfer::transferService.UnregisterHandler(router_transfer::history);
    router_transfer::transferService.UnregisterHandler(router_transfer::encoder);
    router_transfer::transferThread.Terminate();
}
#endif
extern "C" uint32_t PW_RouterTransfer_StackFreeBytes(void) {
#if !defined(PW_TRANSFER_HOST)
    auto handle = router_transfer::workerHandle.load(std::memory_order_acquire);
    return handle ? uxTaskGetStackHighWaterMark(handle) * sizeof(StackType_t) : 0U;
#else
    return 0U;
#endif
}
