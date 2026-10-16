// Archived unary-history test, replaced in CMake by official_transfer_test.cpp.
#include "rpc_can_client.h"
#include "pw_rpc_service.h"
extern "C" {
#include "pw_can_rpc.h"
extern unsigned rpc_test_flash_calls, rpc_test_ascii_calls, rpc_test_snapshot_calls, rpc_test_send_allowed;
}
#include "pw_rpc/internal/packet.h"
#include "pw_log_transfer_readonly.h"
#include "log_download.h"
#include <cassert>
#include <vector>
#include <iostream>
#ifdef _WIN32
#include <windows.h>
#include <cstdlib>
#endif
#include "test_assert.h"
static rpc_can::Client *client;
static std::uint32_t now;
static std::vector<std::array<std::uint8_t, 8>> sent;
extern "C" unsigned rpc_test_now;
extern "C" void RPC_TestSetHistory(const char *, size_t);
extern "C" void RPC_TestClearHistory(void);
static std::uint16_t droppedTransaction;
extern "C" void RPC_TestOnCanFrame(const std::uint8_t bytes[8]) {
    if (std::uint16_t(bytes[1] | (std::uint16_t(bytes[2])<<8)) == droppedTransaction) return;
    if (client) client->receive(CAN_RPC_REPLY_ID, false, false, false, 8, bytes, now);
    std::array<std::uint8_t, 8> frame{}; std::copy_n(bytes, 8, frame.begin()); sent.push_back(frame);
}
static void request(std::uint32_t method) {
    rpc_can::Client c(0xABC000U + now + 1U); client = &c;
    assert(c.begin(method, now));
    assert(!c.begin(method, now));
    const auto end = now + 4900;
    for (; now < end && c.busy(); now += 25) {
        rpc_test_now = now;
        c.tick(now, [](const std::uint8_t *bytes) {
            PW_CanRpc_Receive(CAN_RPC_REQUEST_ID, 0, 0, 0, 8, bytes, now); return true;
        });
        PW_CanRpc_ProtocolService();
        if (now % 100 == 0) PW_CanRpc_MonitorService(now);
    }
    assert(c.state() == rpc_can::State::Success);
    if (method == rpc_readonly::status) assert(rpc_readonly::get32(c.result()+28) == 0U);
    client = nullptr;
}
static auto readChunk(PwLogReadSession &session, std::uint32_t type, std::uint32_t id, std::uint32_t offset,
    std::uint32_t status, std::uint32_t tick, std::array<std::byte, 76> &out) {
    std::uint8_t bytes[32];
    const auto size = log_transfer::encodeRequest(type, id, offset, status, bytes, sizeof(bytes));
    // Desktop request is parsed by actual upstream Chunk codec, not only mocks.
    auto parsed = pw::transfer::internal::Chunk::Parse(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(bytes),size));
    assert(parsed.ok() && parsed->session_id() == id && static_cast<unsigned>(parsed->type()) == type);
    return session.process(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(bytes), size), out, tick);
}
static void sessionTests() {
    PwLogStore_Init();
    std::string text(log_transfer::maxBytes, 'x');
    for (size_t i=0; i<text.size(); ++i) text[i]=static_cast<char>('A'+i%26);
    RPC_TestSetHistory(text.data(), text.size());
    PwLogReadSession session;
    std::array<std::byte,76> out{};
    auto start=readChunk(session,log_transfer::Start,71,0,0,0,out);
    assert(start.ok() && PwLogStore_Used()==16);
    RPC_TestClearHistory(); assert(PwLogStore_Used()==16);
    assert(readChunk(session,log_transfer::Start,72,0,0,1,out).status().IsResourceExhausted());
    assert(readChunk(session,log_transfer::Start,71,0,0,2,out).ok()); // duplicate start reuses snapshot
    std::string received;
    for (std::uint32_t offset=0; offset<text.size(); offset+=32) {
        auto reply=readChunk(session,log_transfer::Continue,71,offset,0,3+offset,out); assert(reply.ok());
        log_transfer::Chunk chunk;
        assert(log_transfer::decode(reinterpret_cast<const std::uint8_t*>(reply->data()),reply->size(),chunk));
        assert(chunk.type==log_transfer::Data && chunk.offset==offset);
        assert(chunk.remaining==text.size()-offset-chunk.size);
        received.append(reinterpret_cast<const char*>(chunk.data),chunk.size);
        // Retransmit same offset must return exactly the same payload.
        auto retry=readChunk(session,log_transfer::Continue,71,offset,0,4+offset,out); assert(retry.ok());
    }
    assert(received==text);
    assert(readChunk(session,log_transfer::Continue,71,text.size(),0,4000,out).ok());
    assert(readChunk(session,log_transfer::Completion,71,0,0,4001,out).ok());
    assert(PwLogStore_Used()==0);
    assert(readChunk(session,log_transfer::Completion,71,0,0,7,out).ok()); // completion ack retry
    assert(readChunk(session,log_transfer::Start,71,0,0,8,out).status().IsFailedPrecondition());
    RPC_TestSetHistory(text.data(),50);
    assert(readChunk(session,log_transfer::Start,73,0,0,0xFFFFFFF0U,out).ok()); RPC_TestClearHistory();
    session.expire(0xFFFFFFF0U+15000U); assert(PwLogStore_Used()==0); // wrap-safe idle timeout
    assert(readChunk(session,log_transfer::Continue,73,0,0,15000,out).status().IsNotFound());
    RPC_TestSetHistory(text.data(),50);
    assert(readChunk(session,log_transfer::Start,74,0,0,0,out).ok()); RPC_TestClearHistory();
    assert(readChunk(session,log_transfer::Continue,74,51,0,1,out).status().IsOutOfRange());
    for (std::uint32_t tick=10000; tick<600000; tick+=10000)
        assert(readChunk(session,log_transfer::Start,74,0,0,tick,out).ok());
    session.expire(600000); assert(PwLogStore_Used()==0); // requests cannot extend absolute deadline
    assert(readChunk(session,log_transfer::Start,75,0,0,600001,out).ok());
    assert(readChunk(session,log_transfer::Completion,75,0,1,600002,out).ok());
    // Strict subset rejects writes, flash resource2, extra/duplicate fields.
    std::uint8_t invalid[32]; auto n=log_transfer::encodeRequest(log_transfer::Start,77,0,0,invalid,sizeof(invalid));
    log_transfer::Chunk checked; assert(log_transfer::decode(invalid,n,checked));
    invalid[n-3]=2; // resource value: stream is session(2),type(2),resource(2),version(2), variable session=1byte
    assert(!session.process(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(invalid),n),out,600003).ok());
    n=log_transfer::encodeRequest(log_transfer::Start,77,0,0,invalid,sizeof(invalid));
    invalid[n++]=0x50; invalid[n++]=1;
    assert(!log_transfer::decode(invalid,n,checked));
}
static void downloadTests() {
    PW_CanRpc_ResetLink(0); now=1000;
    std::string text(log_transfer::maxBytes,'a');
    for (size_t i=0;i<text.size();++i) text[i]=static_cast<char>('0'+i%10);
    RPC_TestSetHistory(text.data(),text.size());
    rpc_can::Client c(5000); client=&c; rpc_can::LogDownload download;
    assert(download.begin(c,12345,now));
    bool cleared=false, dropped=false;
    for (; now<500000 && download.active(); now+=25) {
        rpc_test_now=now;
        if (download.total() && !cleared) { RPC_TestClearHistory(); cleared=true; assert(PwLogStore_Used()==16); }
        if (download.received()>=64 && !dropped) { droppedTransaction=c.transaction(); dropped=true; }
        c.tick(now,[](const std::uint8_t *bytes) { PW_CanRpc_Receive(CAN_RPC_REQUEST_ID,0,0,0,8,bytes,now); return true; });
        PW_CanRpc_ProtocolService();
        if (now%100==0) PW_CanRpc_MonitorService(now);
        download.tick(now);
    }
    assert(download.state()==rpc_can::DownloadState::Done && dropped && cleared);
    assert(download.received()==text.size() && !memcmp(download.data(),text.data(),text.size()));
    assert(PwLogStore_Used()==0); client=nullptr; droppedTransaction=0;
    for (bool cancel : {false,true}) {
        RPC_TestSetHistory(text.data(), cancel ? 150U : 0U);
        rpc_can::Client empty(6000+now); client=&empty; rpc_can::LogDownload d;
        assert(d.begin(empty,12346+now,now)); if (cancel) d.cancel();
        const auto end=now+20000;
        for (;now<end && d.active();now+=25) {
            rpc_test_now=now;
            empty.tick(now,[](const std::uint8_t *bytes){PW_CanRpc_Receive(CAN_RPC_REQUEST_ID,0,0,0,8,bytes,now);return true;});
            PW_CanRpc_ProtocolService(); if(now%100==0) PW_CanRpc_MonitorService(now); d.tick(now);
        }
        assert(d.state()==(cancel ? rpc_can::DownloadState::Cancelled : rpc_can::DownloadState::Done));
        RPC_TestClearHistory(); assert(PwLogStore_Used()==0); client=nullptr;
    }
}
static std::vector<std::uint8_t> encodePacket(std::uint32_t service, std::uint32_t method,
    std::uint32_t type = 0, std::uint32_t channel = 2, std::size_t payloadSize = 0) {
    static std::array<std::byte, 128> storage{}, payload{};
    pw::rpc::internal::Packet packet(static_cast<pw::rpc::internal::pwpb::PacketType>(type), channel, service, method, 99,
        pw::ConstByteSpan(payload.data(), payloadSize));
    const auto encoded = packet.Encode(storage); assert(encoded.ok());
    const auto span = encoded.value();
    return {reinterpret_cast<const std::uint8_t*>(span.data()), reinterpret_cast<const std::uint8_t*>(span.data())+span.size()};
}
int main() {
#ifdef _WIN32
    // Keep assertion failures in ctest stderr; never interrupt the desktop.
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    _set_error_mode(_OUT_TO_STDERR);
#endif
    assert(PW_CanRpc_Init());
    // Host raw encoder must agree with the real upstream Packet parser.
    std::uint8_t encoded[128];
    const auto size = rpc_readonly::encodeRequest(rpc_readonly::status, 0xFFFFFFFU, nullptr, 0, encoded, sizeof(encoded));
    auto parsed = pw::rpc::internal::Packet::FromBuffer(pw::ConstByteSpan(reinterpret_cast<const std::byte*>(encoded), size));
    assert(parsed.ok() && parsed->channel_id() == 2 && parsed->call_id() == 0xFFFFFFFU);
    for (auto method : {rpc_readonly::ping, rpc_readonly::status, rpc_readonly::params, rpc_readonly::diagnostics}) request(method);
    // No CAN call can reach legacy transfer services, channel 1, unknown methods or streams.
    const auto calls = rpc_test_snapshot_calls;
    for (auto bytes : {
        encodePacket(rpc_readonly::hash("pw.transfer.Transfer"), rpc_readonly::hash("Write")),
        encodePacket(rpc_readonly::hash("foc.Transfer"), rpc_readonly::hash("Exchange")),
        encodePacket(rpc_readonly::hash("foc.Control"), rpc_readonly::hash("Ping")),
        encodePacket(rpc_readonly::service, rpc_readonly::hash("Start")),
        encodePacket(rpc_readonly::service, rpc_readonly::status, 2),
        encodePacket(rpc_readonly::service, rpc_readonly::status, 0, 1),
        encodePacket(rpc_readonly::service, rpc_readonly::status, 0, 2, 1)})
        assert(!PW_Rpc_CanProcess(222, bytes.data(), bytes.size()));
    assert(rpc_test_snapshot_calls == calls && rpc_test_flash_calls == 0 && rpc_test_ascii_calls == 0);
    PW_CanRpc_ResetLink(1);
    auto bytes = encodePacket(rpc_readonly::service, rpc_readonly::status);
    assert(!PW_CanRpc_SubmitResponse(223, bytes.data(), bytes.size())); // old link epoch rejected
    CanRpcPacket queued{}; queued.transaction=223; queued.length=static_cast<uint16_t>(bytes.size());
    std::copy(bytes.begin(),bytes.end(),queued.bytes);
    for (size_t i=0; i<CanRpc_FrameCount(queued.length); ++i) {
        uint8_t frame[8]; assert(CanRpc_EncodeFrame(&queued,i,frame));
        PW_CanRpc_Receive(CAN_RPC_REQUEST_ID,0,0,0,8,frame,now);
    }
    PW_CanRpc_ProtocolService();
    const auto count = sent.size(); rpc_test_send_allowed = 0;
    PW_CanRpc_MonitorService(now); PW_CanRpc_MonitorService(now+3000);
    assert(sent.size() == count);
    PW_CanRpcDiagnostics diag{}; PW_CanRpc_GetDiagnostics(&diag);
    assert(diag.response_dropped >= 1 && diag.fifo_overruns == 1);
    rpc_test_send_allowed = 1;
    // Whole-call timeout and unavailable CAN writes are explicit failures, no retries.
    rpc_can::Client timeout;
    assert(timeout.begin(rpc_readonly::ping, 0)); timeout.tick(5000, [](auto *) { assert(false); return true; });
    assert(timeout.state() == rpc_can::State::Timeout);
    rpc_can::Client failure;
    assert(failure.begin(rpc_readonly::ping, 0)); failure.tick(0, [](auto *) { return false; });
    assert(failure.state() == rpc_can::State::SendError);
    // Stale transaction fragments cannot take over a new request.
    rpc_can::Client stale(0xFFF0);
    assert(stale.begin(rpc_readonly::status, 0));
    for (int tick = 0; stale.state() == rpc_can::State::Sending; tick += 75) stale.tick(tick, [](auto *) { return true; });
    std::uint8_t wrong[8] = {CAN_RPC_START, 1, 0, 20, 0, 0, 0, 1};
    stale.receive(CAN_RPC_REPLY_ID, false, false, false, 8, wrong, 1000);
    assert(stale.state() == rpc_can::State::Waiting);
    sessionTests(); downloadTests();
    assert(rpc_test_flash_calls==0 && rpc_test_ascii_calls==0);
    std::cout << "Real Pigweed server + Transfer Chunk, CAN readonly gate, 3056-byte pinned snapshot, dropped-response retry, cancel/empty/deadlines PASS\n";
}
