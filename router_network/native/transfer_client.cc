#include "transfer_client.h"
#include "rpc_readonly_wire.h"
#include "transfer_chunk_validation.h"
#include "pw_transfer/internal/chunk.h"
#include <cstring>
#include <random>

namespace {
constexpr uint32_t service = rpc_readonly::hash("pw.transfer.Transfer");
constexpr uint32_t read = rpc_readonly::hash("Read");
} // namespace
RouterTransferClient::RouterTransferClient(uint16_t id)
    : output(*this), peer(id), channels{}, rpc(channels), thread(chunk, encode),
      transfer(rpc, RN_TRANSFER_CHANNEL_BASE + id, thread, 64), worker([this] { thread.Start(); }) {
    // Transport ID, independent of the upstream call/session ID and R1 seq.
    // Avoid colliding with an old packet after restarting this host process.
    packetId = std::random_device{}();
    if (!packetId)
        packetId = 1;
    rpc.OpenChannel(RN_TRANSFER_CHANNEL_BASE + id, output).IgnoreError();
}
RouterTransferClient::~RouterTransferClient() {
    thread.Terminate();
    worker.join();
}
pw::Status RouterTransferClient::Output::Send(pw::ConstByteSpan bytes) {
    rpc_readonly::Packet packet;
    if (bytes.size() > 128 || !rpc_readonly::decode(reinterpret_cast<const uint8_t *>(bytes.data()),
                                                    bytes.size(), packet))
        return pw::Status::InvalidArgument();
    parent.call.store(packet.call_id);
    auto parsed = pw::transfer::internal::Chunk::Parse(pw::ConstByteSpan(
        reinterpret_cast<const std::byte *>(packet.payload), packet.payload_size));
    if (parsed.ok() && parsed->type() == pw::transfer::internal::Chunk::Type::kCompletion)
        parent.completionSession.store(parsed->session_id());
    const size_t pieces = (bytes.size() + RN_TRANSFER_FRAGMENT - 1) / RN_TRANSFER_FRAGMENT;
    std::lock_guard<std::mutex> lock(parent.mutex);
    if (parent.queue.size() + pieces > 16)
        return pw::Status::ResourceExhausted();
    uint32_t id = parent.packetId++;
    if (!id)
        id = parent.packetId++;
    for (size_t offset = 0; offset < bytes.size(); offset += RN_TRANSFER_FRAGMENT) {
        RouterPacket_t f{};
        f.src = parent.peer;
        f.dst = 1;
        f.type = RN_TRANSFER_TYPE;
        f.seq = parent.sequence++;
        f.ttl = 8;
        f.length = uint16_t(rn_transfer_format(id, reinterpret_cast<const uint8_t *>(bytes.data()),
                                               bytes.size(), offset, f.payload, sizeof(f.payload)));
        if (!f.length)
            return pw::Status::Internal();
        parent.queue.push_back(f);
    }
    return pw::OkStatus();
}
bool RouterTransferClient::begin(uint32_t resource) {
    if (resource != 3 && resource != 4)
        return false;
    auto started = transfer.Read(
        resource, writer, [this](pw::Status status) { terminal.store(int(status.code())); },
        pw::transfer::ProtocolVersion::kVersionTwo, std::chrono::milliseconds(1500),
        std::chrono::milliseconds(1500));
    return started.ok();
}
bool RouterTransferClient::pop(RouterPacket_t &frame) {
    std::lock_guard<std::mutex> lock(mutex);
    if (queue.empty())
        return false;
    const uint32_t now = uint32_t(std::chrono::duration_cast<std::chrono::milliseconds>(
                                      std::chrono::steady_clock::now().time_since_epoch())
                                      .count());
    // Match the existing bounded TCP/ESP ingress limits; do not defeat them
    // by sending an entire file as a burst. This runs in the host I/O owner.
    if (hasSent && uint32_t(now - lastSentMs) < 75U)
        return false;
    hasSent = true;
    lastSentMs = now;
    frame = queue.front();
    queue.pop_front();
    return true;
}
bool RouterTransferClient::receive(const RouterPacket_t &frame, uint32_t now) {
    if (frame.src != 1 || frame.dst != peer || frame.type != RN_TRANSFER_TYPE ||
        frame.length > 224 ||
        std::memchr(frame.payload, '\0', sizeof(frame.payload)) != frame.payload + frame.length)
        return false;
    rn_transfer_view_t view;
    auto state = rn_transfer_feed(&receiver, 1, peer, 0, 0, frame.payload, now, &view);
    if (state != RN_TRANSFER_COMPLETE)
        return state == RN_TRANSFER_PENDING;
    rpc_readonly::Packet p;
    bool accepted = false;
    if (view.size <= 128 && rpc_readonly::decode(view.data, view.size, p) &&
        p.channel_id == RN_TRANSFER_CHANNEL_BASE + peer && p.call_id == call.load() &&
        p.service_id == service && p.method_id == read &&
        (p.type == 7 || p.type == 1 || p.type == 5) && p.status <= 16) {
        auto bytes = pw::ConstByteSpan(reinterpret_cast<const std::byte *>(view.data), view.size);
        auto payload =
            pw::ConstByteSpan(reinterpret_cast<const std::byte *>(p.payload), p.payload_size);
        const bool valid = transfer_can::validV2Chunk(payload);
        if (p.type != 7 || valid) {
            auto chunk = valid ? pw::transfer::internal::Chunk::Parse(payload)
                               : pw::Result<pw::transfer::internal::Chunk>(pw::Status::DataLoss());
            accepted = rpc.ProcessPacket(bytes).ok();
            if (accepted && chunk.ok() &&
                chunk->type() == pw::transfer::internal::Chunk::Type::kCompletionAck &&
                chunk->session_id() == completionSession.load() && completionSession.load())
                ackSeen = true;
            if (accepted && p.type == 5)
                terminal.store(p.status ? int(p.status) : 13);
        }
    }
    rn_transfer_release(&receiver, view.slot);
    return accepted;
}
bool RouterTransferClient::done() {
    std::lock_guard<std::mutex> lock(mutex);
    return terminal.load() >= 0 && queue.empty() && (terminal.load() != 0 || ackSeen);
}
