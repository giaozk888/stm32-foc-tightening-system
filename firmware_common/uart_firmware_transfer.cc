#include "uart_firmware_transfer.h"
#include "uart_firmware_transfer_wire.h"
#include "pw_rpc/server.h"
#include "pw_stream/stream.h"
#include "pw_sync/binary_semaphore.h"
#include "pw_sync/mutex.h"
#include "pw_transfer/transfer.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <mutex>
#if !defined(PW_TRANSFER_HOST)
#include "pw_thread/thread.h"
#include "pw_thread_freertos/context.h"
#include "pw_thread_freertos/options.h"
#endif
namespace uart_fw {
using Type = pw::rpc::internal::pwpb::PacketType;
std::atomic<uint32_t> phase{UART_FW_IDLE}, result{0}, received{0}, rejected{0};
std::atomic<bool> closing{false}, enabled{false};
uint32_t imageSize = 0, call = 0;     // ProtocolTask, published before ProcessPacket.
std::atomic<bool> initialized{false}; // StartupTask publishes initialized RPC state.
bool registered = false;              // ProtocolTask only.
pw::sync::Mutex jobMutex;
pw::sync::BinarySemaphore jobDone;
struct Job {
    uint32_t operation = 0, offset = 0;
    size_t size = 0;
    std::array<uint8_t, 32> data{};
    bool pending = false, ok = false;
} job;
// Only the upstream worker submits; only ProtocolTask executes hardware calls.
bool submit(uint32_t operation, uint32_t offset, const uint8_t *data, size_t size) {
    {
        std::lock_guard<pw::sync::Mutex> lock(jobMutex);
        if (closing.load() || job.pending || size > job.data.size())
            return false;
        job.operation = operation;
        job.offset = offset;
        job.size = size;
        if (size)
            std::memcpy(job.data.data(), data, size);
        job.pending = true;
    }
    jobDone.acquire(); // ProtocolTask services this even during CLOSE.
    std::lock_guard<pw::sync::Mutex> lock(jobMutex);
    return job.ok;
}
class FlashWriter final : public pw::stream::SeekableWriter {
  public:
    void reset() {
        position = highWater = committed = buffered = 0;
    }
    uint32_t total() const {
        return highWater;
    }

  private:
    pw::Status DoWrite(pw::ConstByteSpan data) override {
        if (closing.load() || position > imageSize || data.size() > imageSize - position)
            return pw::Status::OutOfRange();
        const auto *p = reinterpret_cast<const uint8_t *>(data.data());
        size_t left = data.size();
        while (left) {
            if (position < highWater) {
                const size_t n =
                    std::min<size_t>(left, std::min<uint32_t>(32, highWater - position));
                const size_t flashPart =
                    position < committed ? std::min<size_t>(n, committed - position) : 0;
                if (flashPart && !submit(UART_FW_COMPARE, position, p, flashPart))
                    return pw::Status::DataLoss();
                if (n > flashPart && std::memcmp(buffer.data() + position + flashPart - committed,
                                                 p + flashPart, n - flashPart))
                    return pw::Status::DataLoss();
                position += n;
                p += n;
                left -= n;
                continue;
            }
            const size_t n = std::min<size_t>(left, buffer.size() - buffered);
            std::memcpy(buffer.data() + buffered, p, n);
            buffered += n;
            position += n;
            highWater += n;
            p += n;
            left -= n;
            if (buffered == buffer.size() || highWater == imageSize) {
                if (!submit(UART_FW_WRITE, committed, buffer.data(), buffered))
                    return pw::Status::DataLoss();
                committed += buffered;
                buffered = 0;
            }
            received.store(highWater);
        }
        return pw::OkStatus();
    }
    pw::Status DoSeek(ptrdiff_t offset, Whence origin) override {
        const int64_t base = origin == Whence::kBeginning ? 0
                             : origin == Whence::kCurrent ? position
                                                          : imageSize;
        const int64_t target = base + offset;
        if (target < 0 || uint64_t(target) > highWater)
            return pw::Status::OutOfRange();
        position = static_cast<uint32_t>(target);
        return pw::OkStatus();
    }
    size_t DoTell() override {
        return position;
    }
    size_t ConservativeLimit(LimitType type) const override {
        return type == LimitType::kWrite && position <= imageSize ? imageSize - position : 0;
    }
    uint32_t position = 0, highWater = 0, committed = 0;
    size_t buffered = 0;
    std::array<uint8_t, 32> buffer{};
};
FlashWriter writer;
class FirmwareHandler final : public pw::transfer::WriteOnlyHandler {
  public:
    FirmwareHandler() : WriteOnlyHandler(UART_FW_RESOURCE, writer) {}
    pw::Status PrepareWrite() override {
        if (closing.load() || phase.load() != UART_FW_OPEN || !imageSize)
            return pw::Status::FailedPrecondition();
        writer.reset();
        received.store(0);
        phase.store(UART_FW_RECEIVING);
        return pw::OkStatus();
    }
    // No persistent resume or non-zero starting offset in this version.
    pw::Status PrepareWrite(uint32_t) override {
        return pw::Status::PermissionDenied();
    }
    pw::Status FinalizeWrite(pw::Status status) override {
        if (status.ok() && (writer.total() != imageSize || !submit(UART_FW_VERIFY, 0, nullptr, 0)))
            status = pw::Status::DataLoss();
        result.store(static_cast<uint32_t>(status.code()));
        phase.store(status.ok() ? UART_FW_COMPLETE : UART_FW_FAILED);
        return status;
    }
    size_t ResourceSize() const override {
        return imageSize;
    }
};
FirmwareHandler handler;
class Output final : public pw::rpc::ChannelOutput {
  public:
    Output() : ChannelOutput("local-uart-firmware") {}
    size_t MaximumTransmissionUnit() override {
        return UART_FW_PACKET;
    }
    pw::Status Send(pw::ConstByteSpan bytes) override {
        if (!enabled.load() || bytes.size() > UART_FW_PACKET)
            return pw::Status::Unavailable();
        return PW_UartFirmwareTransfer_Send(reinterpret_cast<const uint8_t *>(bytes.data()),
                                            bytes.size())
                   ? pw::OkStatus()
                   : pw::Status::Unavailable();
    }
} output;
std::array<std::byte, UART_FW_PACKET> chunk{}, encode{};
pw::transfer::Thread<0, 1> thread(chunk, encode);
pw::transfer::TransferService serviceObject(thread, 64, std::chrono::seconds(2), 3, 2, 12);
pw::rpc::Channel channels[1];
pw::rpc::Server server(channels);
#if !defined(PW_TRANSFER_HOST)
pw::thread::freertos::StaticContextWithStack<1536> context;
#endif
} // namespace uart_fw
extern "C" void PW_UartFirmwareTransfer_Init(void) {
    using namespace uart_fw;
    if (initialized)
        return;
#if !defined(PW_TRANSFER_HOST)
    auto options = pw::thread::freertos::Options()
                       .set_name("UartFwTransfer")
                       .set_priority(1U)
                       .set_static_context(context);
    pw::Thread(options, [] { thread.Start(); }).detach();
#endif
    serviceObject.set_max_chunk_size_bytes(UART_FW_PACKET);
    server.RegisterService(serviceObject);
    initialized = true;
}
extern "C" void PW_UartFirmwareTransfer_Service(void) {
    using namespace uart_fw;
    {
        std::lock_guard<pw::sync::Mutex> lock(jobMutex);
        if (job.pending) {
            uint32_t value = 0;
            job.ok =
                !closing.load() && PW_UartFirmwareTransfer_Port(job.operation, job.offset,
                                                                job.data.data(), job.size, &value);
            job.pending = false;
            jobDone.release();
        }
    }
    if (closing.load()) {
        // No worker can enqueue another hardware operation once closing is set.
        if (registered && !serviceObject.UnregisterHandler(handler))
            return;
        registered = false;
        server.CloseChannel(UART_FW_CHANNEL).IgnoreError();
        phase.store(UART_FW_IDLE);
        closing.store(false);
    }
}
extern "C" int PW_UartFirmwareTransfer_Process(const uint8_t *data, size_t size, uint8_t local) {
    using namespace uart_fw;
    auto reject = [] {
        rejected.fetch_add(1);
        return 0;
    };
    if (!local || !initialized || closing.load() || !data || !size || size > UART_FW_PACKET)
        return reject();
    auto decoded = pw::rpc::internal::Packet::FromBuffer(
        pw::ConstByteSpan(reinterpret_cast<const std::byte *>(data), size));
    if (!decoded.ok() || !identity(*decoded))
        return reject();
    const auto &p = *decoded;
    if (p.type() == Type::REQUEST) {
        if (!p.payload().empty() || !p.status().ok())
            return reject();
        if (phase.load() == UART_FW_IDLE) {
            uint32_t value = 0;
            if (!PW_UartFirmwareTransfer_Port(UART_FW_PREPARE, 0, nullptr, 0, &value) ||
                value < 8 || value > UART_FW_CAPACITY)
                return reject();
            imageSize = value;
            call = p.call_id();
            result.store(0);
            received.store(0);
            if (!registered) {
                registered = serviceObject.RegisterHandler(handler);
                if (!registered)
                    return reject();
            }
            enabled.store(true);
            if (!server.OpenChannel(UART_FW_CHANNEL, output).ok())
                return reject();
            phase.store(UART_FW_OPEN);
        } else
            return reject(); // Reopening an active RPC would discard its stream.
    } else {
        if (phase.load() == UART_FW_IDLE || p.call_id() != call)
            return reject();
        if (p.type() == Type::CLIENT_STREAM) {
            if (!p.status().ok() || !validChunk(p.payload()))
                return reject();
        } else if (p.type() != Type::CLIENT_REQUEST_COMPLETION && p.type() != Type::CLIENT_ERROR)
            return reject();
        else if (!p.payload().empty())
            return reject();
    }
    return server.ProcessPacket(pw::ConstByteSpan(reinterpret_cast<const std::byte *>(data), size))
        .ok();
}
extern "C" int PW_UartFirmwareTransfer_Close(void) {
    using namespace uart_fw;
    std::lock_guard<pw::sync::Mutex> lock(jobMutex);
    enabled.store(false);
    closing.store(true);
    return 1;
}
extern "C" int PW_UartFirmwareTransfer_Busy(void) {
    return uart_fw::closing.load() || uart_fw::phase.load() != UART_FW_IDLE;
}
extern "C" void PW_UartFirmwareTransfer_GetDiagnostics(UartFirmwareTransferDiagnostics *out) {
    using namespace uart_fw;
    if (out)
        *out = {initialized ? 1U : 0U, uint32_t(PW_UartFirmwareTransfer_Busy()),
                phase.load(),          result.load(),
                received.load(),       rejected.load()};
}
#if defined(PW_TRANSFER_HOST)
extern "C" void PW_UartFirmwareTransfer_Run(void) {
    uart_fw::thread.Start();
}
extern "C" void PW_UartFirmwareTransfer_Stop(void) {
    uart_fw::thread.Terminate();
}
#endif
