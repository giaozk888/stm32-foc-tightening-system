#include "log_download.h"
#include "transfer_can_wire.h"
#include "transfer_chunk_validation.h"
#include "pw_rpc/client.h"
#include "pw_rpc/internal/packet.h"
#include "pw_transfer/client.h"
#include "pw_transfer/internal/chunk.h"
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>

namespace rpc_can {
namespace {
constexpr size_t capacity = 16 * 191;
constexpr uint32_t transferService = rpc_readonly::hash("pw.transfer.Transfer");
constexpr uint32_t transferRead = rpc_readonly::hash("Read");
uint32_t clockMs() {
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}
}
class LogDownload::Impl {
 public:
    class Output final : public pw::rpc::ChannelOutput {
     public:
        explicit Output(Impl& owner) : ChannelOutput("can-transfer-read"), owner_(owner) {}
        size_t MaximumTransmissionUnit() override { return CAN_RPC_MAX_PACKET; }
        pw::Status Send(pw::ConstByteSpan bytes) override {
            if (bytes.empty() || bytes.size() > CAN_RPC_MAX_PACKET) return pw::Status::ResourceExhausted();
            std::lock_guard<std::mutex> guard(owner_.queueMutex_);
            if (owner_.count_ == owner_.queue_.size()) return pw::Status::ResourceExhausted();
            auto packet = pw::rpc::internal::Packet::FromBuffer(bytes);
            if (!packet.ok()) return packet.status();
            owner_.readCall_.store(packet->call_id());
            auto chunk = pw::transfer::internal::Chunk::Parse(packet->payload());
            if (chunk.ok() && chunk->type() == pw::transfer::internal::Chunk::Type::kCompletion)
                owner_.completionSession_.store(chunk->session_id());
            if (chunk.ok() && chunk->type() == pw::transfer::internal::Chunk::Type::kCompletionAck)
                owner_.outgoingAck_.store(true);
            auto& p = owner_.queue_[(owner_.head_ + owner_.count_) % owner_.queue_.size()];
            p.transaction = transfer_can::packetId(owner_.sequence_++);
            p.length = static_cast<uint16_t>(bytes.size());
            std::memcpy(p.bytes, bytes.data(), bytes.size()); ++owner_.count_;
            return pw::OkStatus();
        }
     private:
        Impl& owner_;
    };
    class Writer final : public pw::stream::NonSeekableWriter {
     public:
        explicit Writer(Impl& owner) : owner_(owner) {}
     private:
        pw::Status DoWrite(pw::ConstByteSpan bytes) override {
            const size_t offset = owner_.received_.load();
            if (bytes.size() > capacity - offset) return pw::Status::ResourceExhausted();
            std::memcpy(owner_.bytes_.data() + offset, bytes.data(), bytes.size());
            owner_.received_.store(offset + bytes.size()); return pw::OkStatus();
        }
        size_t ConservativeLimit(LimitType type) const override {
            return type == LimitType::kWrite ? capacity - owner_.received_.load() : 0;
        }
        Impl& owner_;
    };
    explicit Impl(uint32_t sequence = 1) : output_(*this), channels_{pw::rpc::Channel::Create<rpc_readonly::channel>(&output_)},
        rpc_(channels_), thread_(chunk_, encode_), transfer_(rpc_, rpc_readonly::channel, thread_, 64),
        writer_(*this), sequence_(sequence), worker_([this] { thread_.Start(); }) {
        transfer_.set_max_retries(3).IgnoreError();
        transfer_.set_max_lifetime_retries(12).IgnoreError();
        CanRpc_Reset(&rx_);
    }
    ~Impl() { thread_.Terminate(); worker_.join(); }
    uint32_t nextSequence() { std::lock_guard<std::mutex> guard(queueMutex_); return sequence_; }
    bool begin(std::int64_t now) {
        if (state_.load() == DownloadState::Active) return false;
        { std::lock_guard<std::mutex> guard(queueMutex_); head_ = count_ = 0; }
        transmitting_ = false; received_.store(0); total_.store(0); CanRpc_Reset(&rx_);
        finished_.store(false); completionAck_ = peerContact_ = false;
        completionSession_.store(0); outgoingAck_.store(false);
        transportFailed_ = streamClosed_ = false;
        started_ = now; cancelRequested_ = false; state_.store(DownloadState::Active);
        auto result = transfer_.Read(3, writer_, [this](pw::Status status) {
            terminal_.store(status.ok() ? DownloadState::Done : status.IsCancelled() ?
                DownloadState::Cancelled : DownloadState::Failed);
            completionAt_.store(clockMs());
            finished_.store(true);
        }, pw::transfer::ProtocolVersion::kVersionTwo,
#if defined(PW_TRANSFER_TEST_TIMEOUT_MS)
            std::chrono::milliseconds(PW_TRANSFER_TEST_TIMEOUT_MS), std::chrono::milliseconds(PW_TRANSFER_TEST_TIMEOUT_MS));
#else
            std::chrono::seconds(8), std::chrono::seconds(8));
#endif
        if (!result.ok()) { state_.store(DownloadState::Failed); return false; }
        handle_ = *result; return true;
    }
    void cancel() { if (state_.load() == DownloadState::Active && !cancelRequested_) {
        cancelRequested_ = true; handle_.Cancel();
    } }
    void tick(std::int64_t now, const std::function<bool(const std::uint8_t*)>& send) {
        if (state_.load() == DownloadState::Active && now - started_ >= 600000) cancel();
        // Drain completion/cancel packets even after the completion callback.
        if (!transmitting_) {
            std::lock_guard<std::mutex> guard(queueMutex_);
            if (!count_) {
                if (finished_.load()) {
                    const auto terminal = terminal_.load();
                    const bool needAck = !streamClosed_ &&
                        (terminal == DownloadState::Done || (peerContact_ && !outgoingAck_.load()));
#if defined(PW_TRANSFER_TEST_TIMEOUT_MS)
                    constexpr uint32_t completionTimeoutMs = 12000;
#else
                    constexpr uint32_t completionTimeoutMs = 60000;
#endif
                    if (transportFailed_ || (streamClosed_ && terminal == DownloadState::Done) ||
                        (needAck && !completionAck_ &&
                        uint32_t(clockMs() - completionAt_.load()) >= completionTimeoutMs))
                        state_.store(DownloadState::Failed);
                    else if (!needAck || completionAck_) state_.store(terminal);
                }
                return;
            }
            tx_ = queue_[head_]; head_ = (head_ + 1) % queue_.size(); --count_;
            frame_ = 0; transmitting_ = true; nextSend_ = now;
        }
        if (now < nextSend_) return;
        std::uint8_t bytes[8];
        if (!CanRpc_EncodeFrame(&tx_, frame_, bytes) || !send(bytes)) {
            transportFailed_ = true; cancel(); transmitting_ = false; return;
        }
        nextSend_ = now + 75;
        if (++frame_ == CanRpc_FrameCount(tx_.length)) transmitting_ = false;
    }
    void receive(std::uint32_t id, bool extended, bool remote, bool error,
        std::uint8_t length, const std::uint8_t* bytes, std::int64_t now) {
        if (id != CAN_RPC_REPLY_ID || !bytes || length != 8 || extended || remote || error ||
            !transfer_can::isStream(uint16_t(bytes[1] | uint16_t(bytes[2]) << 8))) return;
        const auto result = CanRpc_Feed(&rx_, CAN_RPC_REPLY_ID, id, extended, remote, error, 0,
            length, bytes, static_cast<std::uint32_t>(now));
        if (result != CAN_RPC_COMPLETE) return; // Upstream timeouts/retries handle missing or damaged packets.
        auto packet = pw::rpc::internal::Packet::FromBuffer(pw::ConstByteSpan(
            reinterpret_cast<const std::byte*>(rx_.packet.bytes), rx_.packet.length));
        if (!packet.ok() || packet->channel_id() != rpc_readonly::channel ||
            packet->service_id() != transferService || packet->method_id() != transferRead ||
            packet->call_id() != readCall_.load()) return;
        const bool validChunk = transfer_can::validV2Chunk(packet->payload());
        if (packet->type() == pw::rpc::internal::pwpb::PacketType::SERVER_STREAM && !validChunk) return;
        auto chunk = validChunk ? pw::transfer::internal::Chunk::Parse(packet->payload()) :
            pw::Result<pw::transfer::internal::Chunk>(pw::Status::DataLoss());
        if (chunk.ok() && chunk->type() == pw::transfer::internal::Chunk::Type::kData &&
            chunk->remaining_bytes().has_value()) {
            const uint64_t total = uint64_t(chunk->offset()) + chunk->payload().size() + *chunk->remaining_bytes();
            if (total <= capacity) total_.store(static_cast<size_t>(total));
        }
        const auto status = rpc_.ProcessPacket(pw::ConstByteSpan(
            reinterpret_cast<const std::byte*>(rx_.packet.bytes), rx_.packet.length));
        if (status.ok() && chunk.ok()) {
            if (chunk->type() == pw::transfer::internal::Chunk::Type::kStartAck) peerContact_ = true;
            if (chunk->type() == pw::transfer::internal::Chunk::Type::kCompletionAck &&
                completionSession_.load() && chunk->session_id() == completionSession_.load())
                completionAck_ = true;
        }
        if (status.ok() && packet->type() == pw::rpc::internal::pwpb::PacketType::SERVER_ERROR)
            streamClosed_ = true;
    }
    Output output_;
    pw::rpc::Channel channels_[1];
    pw::rpc::Client rpc_;
    std::array<std::byte, 96> chunk_{};
    std::array<std::byte, 128> encode_{};
    pw::transfer::Thread<1, 0> thread_;
    pw::transfer::Client transfer_;
    Writer writer_;
    pw::transfer::Client::Handle handle_;
    std::array<std::uint8_t, capacity> bytes_{};
    std::atomic<size_t> received_{0}, total_{0};
    std::atomic<DownloadState> state_{DownloadState::Idle};
    std::atomic<DownloadState> terminal_{DownloadState::Idle};
    std::atomic<bool> finished_{false};
    std::atomic<bool> outgoingAck_{false};
    std::atomic<uint32_t> readCall_{0}, completionSession_{0}, completionAt_{0};
    std::mutex queueMutex_;
    std::array<CanRpcPacket, 4> queue_{};
    size_t head_ = 0, count_ = 0, frame_ = 0;
    uint32_t sequence_ = 1; // Protected by queueMutex_; never reused within a read.
    CanRpcPacket tx_{};
    CanRpcReceiver rx_{};
    bool transmitting_ = false, cancelRequested_ = false, transportFailed_ = false;
    bool completionAck_ = false, peerContact_ = false, streamClosed_ = false; // UI-thread owned.
    std::int64_t started_ = 0, nextSend_ = 0;
    std::thread worker_;
};
LogDownload::LogDownload() = default;
LogDownload::~LogDownload() = default;
bool LogDownload::begin(Client& query, std::uint32_t seed, std::int64_t now) {
    if (query.busy() || active() || !seed) return false;
    // A failure before peer contact may leave a completion handshake pending.
    // Retire that worker before a new export, without reusing CAN packet IDs.
    if (impl_ && (state() == DownloadState::Failed || state() == DownloadState::Cancelled)) {
        const auto sequence = impl_->nextSequence(); impl_.reset();
        impl_ = std::make_unique<Impl>(sequence);
    }
    if (!impl_) impl_ = std::make_unique<Impl>();
    return impl_->begin(now);
}
void LogDownload::tick(std::int64_t now, const std::function<bool(const std::uint8_t*)>& send) {
    if (impl_) impl_->tick(now, send);
}
void LogDownload::receive(std::uint32_t id, bool e, bool r, bool error, std::uint8_t n,
    const std::uint8_t* bytes, std::int64_t now) { if (impl_) impl_->receive(id, e, r, error, n, bytes, now); }
void LogDownload::cancel() { if (impl_) impl_->cancel(); }
bool LogDownload::canCancel() const { return active() && !impl_->cancelRequested_ && !impl_->finished_.load(); }
bool LogDownload::active() const { return state() == DownloadState::Active; }
DownloadState LogDownload::state() const { return impl_ ? impl_->state_.load() : DownloadState::Idle; }
std::size_t LogDownload::received() const { return impl_ ? impl_->received_.load() : 0; }
std::size_t LogDownload::total() const { return impl_ ? impl_->total_.load() : 0; }
const std::uint8_t* LogDownload::data() const { return impl_ ? impl_->bytes_.data() : nullptr; }
}
