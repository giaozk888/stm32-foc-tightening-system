#include "log_download.h"
#include "pw_buffer_test_heap.h"
#include "official_log_transfer.h"
#include "transfer_can_wire.h"
#include "transfer_chunk_validation.h"
#include "pw_rpc_service.h"
#include "pw_can_rpc.h"
#include "pw_rpc/internal/packet.h"
#include "motor_rpc_wire.h"
#include "pw_transfer/internal/chunk.h"
#include <chrono>
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>
#include "test_assert.h"
#ifdef _WIN32
#include <windows.h>
#include <timeapi.h>
#include <cstdlib>
#endif

static std::recursive_mutex critical;
extern "C" void RPC_TestLock() { critical.lock(); }
extern "C" void RPC_TestUnlock() { critical.unlock(); }
extern "C" void RPC_TestSetHistory(const char*, size_t);
extern "C" void RPC_TestClearHistory();
extern "C" void PW_Rpc_CanTransferTimeout(uint32_t);
extern "C" unsigned rpc_test_now, rpc_test_flash_calls, rpc_test_ascii_calls;
static rpc_can::Client* query;
static rpc_can::LogDownload* download;
static uint32_t now;
static CanRpcReceiver inspection{};
static bool droppingPacket;
static unsigned dropAtPacket, packetIndex, droppedPackets;
static unsigned dataPackets, startPackets;
static bool rawCapture, rawComplete;
static bool malformedRepliesInjected;
static void injectMalformedReplies(uint32_t call) {
    // Valid RPC envelope and CRC, but unsafe optional-field combinations.
    // The HMI must drop these before the upstream thread sees their payloads.
    for (const auto& payload : {std::vector<std::byte>{std::byte{0x60}, std::byte{1}},
        std::vector<std::byte>{std::byte{0x60}, std::byte{1}, std::byte{0x50}, std::byte{4}}}) {
        std::array<std::byte, CAN_RPC_MAX_PACKET> storage{};
        pw::rpc::internal::Packet packet(pw::rpc::internal::pwpb::PacketType::SERVER_STREAM,
            2, rpc_readonly::hash("pw.transfer.Transfer"), rpc_readonly::hash("Read"), call,
            pw::ConstByteSpan(payload.data(), payload.size()));
        auto encoded = packet.Encode(storage); assert(encoded.ok());
        CanRpcPacket frames{};
        frames.transaction = transfer_can::packetId(32001 + payload.size());
        frames.length = static_cast<uint16_t>(encoded->size());
        std::memcpy(frames.bytes, encoded->data(), encoded->size());
        for (unsigned i = 0; i < CanRpc_FrameCount(frames.length); ++i) {
            uint8_t frame[8]; assert(CanRpc_EncodeFrame(&frames, i, frame));
            download->receive(CAN_RPC_REPLY_ID, false, false, false, 8, frame, now);
        }
        assert(download->active());
    }
    malformedRepliesInjected = true;
}
extern "C" void RPC_TestOnCanFrame(const uint8_t* frame) {
    if (rawCapture) {
        rawComplete = CanRpc_Feed(&inspection, CAN_RPC_REPLY_ID, CAN_RPC_REPLY_ID,
            0, 0, 0, 0, 8, frame, now) == CAN_RPC_COMPLETE;
        return;
    }
    const uint16_t transaction = frame[1] | uint16_t(frame[2]) << 8;
    if (transfer_can::isStream(transaction)) {
        if (frame[0] == CAN_RPC_START) {
            droppingPacket = ++packetIndex == dropAtPacket;
            if (droppingPacket) ++droppedPackets;
        }
        if (droppingPacket) return;
        const auto result = CanRpc_Feed(&inspection, CAN_RPC_REPLY_ID, CAN_RPC_REPLY_ID,
            0, 0, 0, 0, 8, frame, now);
        uint32_t injectCall = 0;
        if (result == CAN_RPC_COMPLETE) {
            auto packet = pw::rpc::internal::Packet::FromBuffer(pw::ConstByteSpan(
                reinterpret_cast<const std::byte*>(inspection.packet.bytes), inspection.packet.length));
            assert(packet.ok());
            auto chunk = pw::transfer::internal::Chunk::Parse(packet->payload());
            if (chunk.ok()) {
                if (chunk->type() == pw::transfer::internal::Chunk::Type::kData) ++dataPackets;
                if (chunk->type() == pw::transfer::internal::Chunk::Type::kStartAck) {
                    ++startPackets;
                    if (!malformedRepliesInjected) injectCall = packet->call_id();
                }
            }
        }
        if (download) download->receive(CAN_RPC_REPLY_ID, false, false, false, 8, frame, now);
        if (download && injectCall) injectMalformedReplies(injectCall);
    } else if (query) query->receive(CAN_RPC_REPLY_ID, false, false, false, 8, frame, now);
}
static bool sendCanFrame(const uint8_t* frame) {
    PW_CanRpc_Receive(CAN_RPC_REQUEST_ID, 0, 0, 0, 8, frame, now); return true;
}
static void tick() {
    rpc_test_now = now;
    if (download) download->tick(now, sendCanFrame);
    if (query) query->tick(now, sendCanFrame);
    PW_CanRpc_ProtocolService();
    if (now % 100 == 0) PW_CanRpc_MonitorService(now);
    now += 25;
#ifdef _WIN32
    Sleep(1); // MinGW sleep_for is unsuitable for this accelerated clock.
#else
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
#endif
}
static void queryTests() {
    rpc_can::Client rollover(0x8000), afterRollover(0x8001);
    assert(rollover.begin(rpc_readonly::ping, now));
    assert(afterRollover.begin(rpc_readonly::ping, now));
    assert(rollover.transaction() == 1 && afterRollover.transaction() == 2);
    assert(!transfer_can::isStream(rollover.transaction()));
    for (auto method : {rpc_readonly::ping, rpc_readonly::status, rpc_readonly::params, rpc_readonly::diagnostics}) {
        rpc_can::Client client(now + 1); query = &client;
        assert(client.begin(method, now));
        while (client.busy()) tick();
        assert(client.state() == rpc_can::State::Success);
        query = nullptr;
    }
    std::array<std::byte, 128> storage{};
    // The original read-only profile must not acquire actuator-service
    // authority merely because the new shared headers exist.
    std::array<uint8_t, 128> motorBytes{};
    MotorControlRequest motorRequest{1, 55, 7, 123, 1};
    for (auto method : {motor_rpc::status, motor_rpc::arm, motor_rpc::start, motor_rpc::stop}) {
        auto length = motor_rpc::encodeRequest(method, 1, motorRequest,
                                               motorBytes.data(), motorBytes.size());
        assert(length && !PW_Rpc_CanProcess(23, motorBytes.data(), length));
    }
    for (auto serviceMethod : {
        std::pair{rpc_readonly::hash("pw.transfer.Transfer"), rpc_readonly::hash("Write")},
        std::pair{rpc_readonly::hash("pw.transfer.Transfer"), rpc_readonly::hash("GetResourceStatus")},
        std::pair{rpc_readonly::hash("foc.Transfer"), rpc_readonly::hash("Exchange")},
        std::pair{rpc_readonly::service, rpc_readonly::logChunk}}) {
        pw::rpc::internal::Packet packet(pw::rpc::internal::pwpb::PacketType::REQUEST,
            2, serviceMethod.first, serviceMethod.second, 1);
        auto bytes = packet.Encode(storage); assert(bytes.ok());
        assert(!PW_Rpc_CanProcess(transfer_can::packetId(1),
            reinterpret_cast<const uint8_t*>(bytes->data()), bytes->size()));
    }
    using Chunk = pw::transfer::internal::Chunk;
    std::array<std::byte, 96> chunkStorage{};
    auto rejectChunk = [&](const Chunk& chunk) {
        auto encoded = chunk.Encode(chunkStorage); assert(encoded.ok());
        pw::rpc::internal::Packet packet(pw::rpc::internal::pwpb::PacketType::CLIENT_STREAM,
            2, rpc_readonly::hash("pw.transfer.Transfer"), rpc_readonly::hash("Read"), 7, *encoded);
        auto bytes = packet.Encode(storage); assert(bytes.ok());
        assert(!PW_Rpc_CanProcess(transfer_can::packetId(2),
            reinterpret_cast<const uint8_t*>(bytes->data()), bytes->size()));
    };
    Chunk start(pw::transfer::ProtocolVersion::kVersionTwo, Chunk::Type::kStart);
    start.set_desired_session_id(7).set_resource_id(2).set_window_end_offset(64);
    rejectChunk(start); // Firmware writes are never a log resource.
    start.set_resource_id(3).set_initial_offset(1); rejectChunk(start);
    start.set_initial_offset(0).set_window_end_offset(65); rejectChunk(start);
    Chunk parameters(pw::transfer::ProtocolVersion::kVersionTwo, Chunk::Type::kParametersContinue);
    parameters.set_session_id(7).set_offset(0).set_window_end_offset(65); rejectChunk(parameters);
    parameters.set_window_end_offset(64).set_offset(3057); rejectChunk(parameters);
    Chunk data(pw::transfer::ProtocolVersion::kVersionTwo, Chunk::Type::kData);
    data.set_session_id(7).set_payload(pw::ConstByteSpan(storage.data(), 1)); rejectChunk(data);
    auto rejectMalformed = [&](pw::ConstByteSpan payload) {
        assert(!transfer_can::validV2Chunk(payload));
        pw::rpc::internal::Packet packet(pw::rpc::internal::pwpb::PacketType::CLIENT_STREAM,
            2, rpc_readonly::hash("pw.transfer.Transfer"), rpc_readonly::hash("Read"), 7, payload);
        auto bytes = packet.Encode(storage); assert(bytes.ok());
        assert(!PW_Rpc_CanProcess(transfer_can::packetId(3),
            reinterpret_cast<const uint8_t*>(bytes->data()), bytes->size()));
    };
    const std::array<std::byte, 2> noType{std::byte{0x60}, std::byte{1}};
    const std::array<std::byte, 4> noStatus{std::byte{0x60}, std::byte{1}, std::byte{0x50}, std::byte{4}};
    rejectMalformed(noType); rejectMalformed(noStatus);
    const std::array<std::byte, 6> explicitOk{std::byte{0x60}, std::byte{1},
        std::byte{0x50}, std::byte{4}, std::byte{0x40}, std::byte{0}};
    assert(transfer_can::validV2Chunk(explicitOk)); // Presence matters even for status OK=0.
    uint32_t random = 0x474;
    std::array<std::byte, 128> wrappedStorage{};
    for (unsigned i = 0; i < 20000; ++i) {
        for (auto& byte : storage) { random = random * 1664525U + 1013904223U; byte = std::byte(random >> 24); }
        assert(!PW_Rpc_CanProcess(transfer_can::packetId(i),
            reinterpret_cast<const uint8_t*>(storage.data()), 1 + i % storage.size()));
        pw::rpc::internal::Packet wrapped(pw::rpc::internal::pwpb::PacketType::CLIENT_STREAM,
            2, rpc_readonly::hash("pw.transfer.Transfer"), rpc_readonly::hash("Read"), 7,
            pw::ConstByteSpan(storage.data(), 1 + i % chunkStorage.size()));
        auto bytes = wrapped.Encode(wrappedStorage); assert(bytes.ok());
        (void)PW_Rpc_CanProcess(transfer_can::packetId(i),
            reinterpret_cast<const uint8_t*>(bytes->data()), bytes->size());
    }
    PW_CanRpc_ResetLink(0); PW_CanRpc_ProtocolService();
}
static void fullPacketPacingTest() {
    std::array<uint8_t, CAN_RPC_MAX_PACKET> payload{};
    for (size_t i = 0; i < payload.size(); ++i) payload[i] = uint8_t(i);
    CanRpc_Reset(&inspection); rawComplete = false; rawCapture = true;
    PW_CanRpcDiagnostics before{}, after{}; PW_CanRpc_GetDiagnostics(&before);
    assert(PW_CanRpc_SubmitStreamResponse(transfer_can::packetId(32000), PW_CanRpc_LinkEpoch(),
        payload.data(), payload.size()));
    const auto deadline = now + 5000;
    while (!rawComplete && now < deadline) tick();
    assert(rawComplete && inspection.packet.length == payload.size());
    assert(std::memcmp(inspection.packet.bytes, payload.data(), payload.size()) == 0);
    PW_CanRpc_GetDiagnostics(&after); assert(before.response_dropped == after.response_dropped);
    rawCapture = false;
}
static void readerTests() {
    const std::string text = "immutable log records across boundaries";
    RPC_TestSetHistory(text.data(), text.size());
    official_log_transfer::HistoryHandler handler;
    official_log_transfer::HistoryReader reader;
    assert(reader.prepare().ok());
    assert(reader.prepare().IsResourceExhausted());
    RPC_TestClearHistory();
    std::array<std::byte, 200> bytes{};
    assert(reader.Read(bytes).ok());
    assert(std::memcmp(bytes.data(), text.data(), text.size()) == 0);
    assert(reader.Seek(2).ok());
    auto part = reader.Read(pw::ByteSpan(bytes.data(), 3)); assert(part.ok());
    assert(std::memcmp(bytes.data(), text.data() + 2, 3) == 0);
    assert(reader.Seek(-1).IsOutOfRange());
    reader.release(); assert(PwLogStore_Used() == 0);
    assert(handler.PrepareWrite().IsPermissionDenied());
    assert(handler.PrepareRead(4).IsUnimplemented());
    RPC_TestSetHistory(text.data(), text.size());
    handler.setTime(UINT32_MAX - 100);
    assert(handler.PrepareRead().ok()); RPC_TestClearHistory();
    handler.setTime(uint32_t(UINT32_MAX - 100 + official_log_transfer::sessionLimitMs - 1));
    assert(!handler.expired());
    handler.setTime(uint32_t(UINT32_MAX - 100 + official_log_transfer::sessionLimitMs));
    assert(handler.expired()); handler.FinalizeRead(pw::Status::Aborted());
    assert(PwLogStore_Used() == 0 && !handler.expired());
}
static void downloadTest(const std::string& text, unsigned dropPacket, bool cancel, bool reset, bool reuse = false) {
    PW_CanRpc_ResetLink(0); PW_CanRpc_ProtocolService();
    RPC_TestSetHistory(text.data(), text.size());
    rpc_can::Client idle;
    rpc_can::LogDownload client;
    download = &client;
    dropAtPacket = dropPacket; packetIndex = 0; droppingPacket = false; CanRpc_Reset(&inspection);
    const auto initialDrops = droppedPackets;
    const auto initialData = dataPackets;
    assert(client.begin(idle, 1, now));
    bool cleared = false, action = false;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(45);
    while (client.active() && std::chrono::steady_clock::now() < deadline) {
        tick();
        if (!cleared && dataPackets > initialData) { RPC_TestClearHistory(); cleared = true; }
        if ((cancel || reset) && client.received() && !action) {
            if (cancel) client.cancel(); else PW_CanRpc_ResetLink(1);
            action = true;
        }
    }
    PW_CanRpcDiagnostics diagnostics{}; PW_CanRpc_GetDiagnostics(&diagnostics);
    std::cerr << "download: state=" << int(client.state()) << " bytes=" << client.received()
        << " total=" << client.total() << " start=" << startPackets << " data=" << dataPackets << '\n';
    std::cerr << "CAN rejected=" << diagnostics.rejected << " tx_drop=" << diagnostics.response_dropped
        << " now=" << now << '\n';
    assert(!client.active());
    if (dropPacket) assert(droppedPackets == initialDrops + 1);
    if (cancel) assert(client.state() == rpc_can::DownloadState::Cancelled);
    else if (reset) assert(client.state() == rpc_can::DownloadState::Failed);
    else {
        assert(client.state() == rpc_can::DownloadState::Done);
        assert(client.received() == text.size());
        assert(!text.size() || std::memcmp(client.data(), text.data(), text.size()) == 0);
    }
    if (reuse) {
        const std::string next = "second export using the same official RPC stream\n";
        RPC_TestSetHistory(next.data(), next.size());
        assert(client.begin(idle, 2, now));
        const auto secondDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
        while (client.active() && std::chrono::steady_clock::now() < secondDeadline) tick();
        PW_CanRpc_GetDiagnostics(&diagnostics);
        std::cerr << "reuse: state=" << int(client.state()) << " bytes=" << client.received()
            << " rejected=" << diagnostics.rejected << " start=" << startPackets
            << " complete=" << diagnostics.complete << " tx_drop=" << diagnostics.response_dropped << '\n';
        assert(client.state() == rpc_can::DownloadState::Done);
        assert(client.received() == next.size());
        assert(std::memcmp(client.data(), next.data(), next.size()) == 0);
    }
    download = nullptr;
    RPC_TestClearHistory(); assert(PwLogStore_Used() == 0); // No ResetLink masking leaked refs.
    PW_CanRpc_ResetLink(0); PW_CanRpc_ProtocolService();
    RPC_TestClearHistory(); assert(PwLogStore_Used() == 0);
}
static void serverTimeoutTest(const std::string& text) {
    PW_CanRpc_ResetLink(0); PW_CanRpc_ProtocolService();
    RPC_TestSetHistory(text.data(), text.size());
    rpc_can::Client idle;
    rpc_can::LogDownload client; download = &client;
    dropAtPacket = packetIndex = 0; droppingPacket = false;
    CanRpc_Reset(&inspection);
    assert(client.begin(idle, 1, now));
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (client.received() < 64 && std::chrono::steady_clock::now() < deadline) tick();
    assert(client.received() >= 64);
    RPC_TestClearHistory(); assert(PwLogStore_Used() > 0);
    // Stop feeding client parameters; let the server finish its current window.
    download = nullptr;
    for (unsigned i = 0; i < 300; ++i) tick();
    PW_Rpc_CanTransferTimeout(1); // Exercise the genuine upstream server timeout event.
    assert(PwLogStore_Used() == 0);
    download = &client;
    const auto finishDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
    while (client.active() && std::chrono::steady_clock::now() < finishDeadline) tick();
    assert(client.state() == rpc_can::DownloadState::Failed);
    download = nullptr;
    PW_CanRpc_ResetLink(0); PW_CanRpc_ProtocolService();
}
static void absoluteExpiryTest(const std::string& text) {
    PW_CanRpc_ResetLink(0); PW_CanRpc_ProtocolService();
    RPC_TestSetHistory(text.data(), text.size());
    rpc_can::Client idle;
    rpc_can::LogDownload client; download = &client;
    dropAtPacket = packetIndex = 0; droppingPacket = false;
    CanRpc_Reset(&inspection);
    assert(client.begin(idle, 1, now));
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!client.received() && std::chrono::steady_clock::now() < deadline) tick();
    assert(client.received());
    RPC_TestClearHistory(); assert(PwLogStore_Used() > 0);
    PW_Rpc_CanTick(now + official_log_transfer::sessionLimitMs + 1);
    assert(PwLogStore_Used() == 0); // Production expiry path, not a ResetLink shortcut.
    download = nullptr;
    PW_CanRpc_ResetLink(0); PW_CanRpc_ProtocolService();
}
int main() {
#ifdef _WIN32
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    _set_error_mode(_OUT_TO_STDERR);
    assert(timeBeginPeriod(1) == TIMERR_NOERROR);
#endif
    std::thread worker(PW_Rpc_CanTransferRun);
    assert(PW_CanRpc_Init());
    PwLogStore_Init();
    readerTests(); fullPacketPacingTest(); queryTests();
    std::string text(official_log_transfer::capacity, 'x');
    for (size_t i = 0; i < text.size(); ++i) text[i] = char('A' + i % 26);
    downloadTest(text, 0, false, false, true);
    downloadTest(text, 3, false, false); // Lost data: upstream requests a seek/retransmit.
    downloadTest("short log\n", 1, false, false); // Lost handshake.
    downloadTest("short log\n", 3, false, false); // Lost completion acknowledgement.
    downloadTest("", 0, false, false);
    downloadTest(text, 0, true, false);
    downloadTest(text, 0, false, true);
    serverTimeoutTest(text);
    absoluteExpiryTest(text);
    assert(startPackets && dataPackets && malformedRepliesInjected);
    assert(!rpc_test_flash_calls && !rpc_test_ascii_calls);
    PW_Rpc_CanTransferStop(); worker.join();
    assert(PW_BufferTest_LiveAllocations() == 0);
#ifdef _WIN32
    timeEndPeriod(1);
#endif
    std::cout << "Official Transfer.Read over fragmented CAN: full/empty/reuse, lost StartAck/Data/CompletionAck, cancel/reset/idle/absolute expiry, pinned seekable history, write isolation and fuzz PASS\n";
}
