#include "firmware_transfer_client.h"
#include "pw_transfer/internal/chunk.h"
FirmwareTransferClient::FirmwareTransferClient(pw::stream::Reader &input)
    : output(*this), reader(input), rpc(channels), thread(chunk, encode),
      transfer(rpc, UART_FW_CHANNEL, thread, 64), worker([this] { thread.Start(); }) {
    rpc.OpenChannel(UART_FW_CHANNEL, output).IgnoreError();
}
FirmwareTransferClient::~FirmwareTransferClient() {
    thread.Terminate();
    worker.join();
}
pw::Status FirmwareTransferClient::Output::Send(pw::ConstByteSpan data) {
    if (data.empty() || data.size() > UART_FW_PACKET)
        return pw::Status::OutOfRange();
    auto p = pw::rpc::internal::Packet::FromBuffer(data);
    if (!p.ok() || !uart_fw::identity(*p))
        return pw::Status::InvalidArgument();
    auto c = pw::transfer::internal::Chunk::Parse(p->payload());
    std::lock_guard<std::mutex> lock(parent.mutex);
    if (parent.queue.size() >= 8)
        return pw::Status::ResourceExhausted();
    const auto *bytes = reinterpret_cast<const uint8_t *>(data.data());
    parent.queue.emplace_back(bytes, bytes + data.size());
    parent.call.store(p->call_id());
    if (c.ok() && c->type() == pw::transfer::internal::Chunk::Type::kCompletionAck)
        parent.ackQueued.store(true);
    return pw::OkStatus();
}
bool FirmwareTransferClient::begin() {
    return transfer
        .Write(
            UART_FW_RESOURCE, reader,
            [this](pw::Status s) { terminal.store(static_cast<int>(s.code())); },
            pw::transfer::ProtocolVersion::kVersionTwo, std::chrono::seconds(3),
            std::chrono::seconds(3))
        .ok();
}
bool FirmwareTransferClient::pop(std::vector<uint8_t> &packet) {
    std::lock_guard<std::mutex> lock(mutex);
    if (queue.empty())
        return false;
    packet = std::move(queue.front());
    queue.pop_front();
    return true;
}
bool FirmwareTransferClient::receive(const uint8_t *data, size_t size) {
    if (!data || !size || size > UART_FW_PACKET)
        return false;
    const auto bytes = pw::ConstByteSpan(reinterpret_cast<const std::byte *>(data), size);
    auto p = pw::rpc::internal::Packet::FromBuffer(bytes);
    if (!p.ok() || !uart_fw::identity(*p) || p->call_id() != call.load())
        return false;
    using Type = pw::rpc::internal::pwpb::PacketType;
    if (p->type() == Type::SERVER_STREAM) {
        if (!uart_fw::validChunk(p->payload()))
            return false;
    } else if (p->type() != Type::RESPONSE && p->type() != Type::SERVER_ERROR)
        return false;
    return rpc.ProcessPacket(bytes).ok();
}
bool FirmwareTransferClient::done() {
    std::lock_guard<std::mutex> lock(mutex);
    return terminal.load() >= 0 && queue.empty() && (terminal.load() != 0 || ackQueued.load());
}
