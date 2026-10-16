#include "rpc_motor_client.h"
#include "pw_can_rpc.h"
#include "pw_rpc_service.h"
#include "pw_rpc/internal/packet.h"
#include "test_assert.h"
#include <mutex>
#include <thread>
#include <cstdio>
static std::recursive_mutex critical;
extern "C" void RPC_TestLock() {
    critical.lock();
}
extern "C" void RPC_TestUnlock() {
    critical.unlock();
}
extern "C" unsigned rpc_test_now, rpc_test_flash_calls, rpc_test_ascii_calls;
static rpc_can::MotorClient client(101);
static rpc_can::Client readOnly(801);
static unsigned serviceCalls;
extern "C" void PW_MotorControl_Invoke(MotorControlOpcode op, const MotorControlRequest *req,
                                       MotorControlReply *reply) {
    ++serviceCalls;
    *reply = {};
    reply->operation_id = req->operation_id;
    reply->decision = op == MOTOR_RPC_STATUS ? MOTOR_RPC_OK : MOTOR_RPC_DISABLED;
    reply->view.blockers = MOTOR_BLOCK_REMOTE_DISABLED | MOTOR_BLOCK_ESTOP_UNVERIFIED;
    reply->view.safe_latched = 1;
    reply->view.recipe_crc = 0x12345678;
    // No hardware/motion hook in this mock; actual port is separately tested.
}
extern "C" void RPC_TestOnCanFrame(const uint8_t *bytes) {
    client.receive(CAN_RPC_REPLY_ID, false, false, false, 8, bytes, rpc_test_now);
    readOnly.receive(CAN_RPC_REPLY_ID, false, false, false, 8, bytes, rpc_test_now);
}
static void tick() {
    rpc_test_now += 5;
    const auto send = [](const uint8_t *bytes) {
        PW_CanRpc_Receive(CAN_RPC_REQUEST_ID, 0, 0, 0, 8, bytes, rpc_test_now);
        return true;
    };
    client.tick(rpc_test_now, send);
    readOnly.tick(rpc_test_now, send);
    PW_CanRpc_ProtocolService();
    if (rpc_test_now % 100 == 0)
        PW_CanRpc_MonitorService(rpc_test_now);
}
static void request(uint32_t method, MotorControlDecision expected) {
    MotorControlRequest req{1, 900, 1, 0x12345678, 1};
    assert(client.begin(method, rpc_test_now, req));
    for (unsigned n = 0; client.busy() && n < 1100; ++n)
        tick();
    assert(client.state() == rpc_can::State::Success);
    assert(client.reply().decision == uint32_t(expected));
    assert(client.remoteStatus() == (expected == MOTOR_RPC_OK ? 0U : 9U));
}
static void clientFaultTests() {
    rpc_can::MotorClient timeout;
    assert(timeout.begin(motor_rpc::status, 0));
    unsigned sends = 0;
    timeout.tick(5000, [&](auto *) {
        ++sends;
        return true;
    });
    assert(timeout.state() == rpc_can::State::Timeout && sends == 0);
    timeout.tick(6000, [&](auto *) {
        ++sends;
        return true;
    });
    assert(sends == 0); // Timeout cannot initiate an automatic retry.
    rpc_can::MotorClient failure;
    assert(failure.begin(motor_rpc::status, 0));
    failure.tick(0, [](auto *) { return false; });
    assert(failure.state() == rpc_can::State::SendError);

    // Genuine upstream reply encoder, with valid CAN packet CRC. Corrupt
    // business/correlation data must not become a successful client result.
    for (unsigned variant = 0; variant < 6; ++variant) {
        rpc_can::MotorClient c(123);
        assert(c.begin(motor_rpc::status, 0));
        for (unsigned t = 0; c.state() == rpc_can::State::Sending; t += 75)
            c.tick(t, [](auto *) { return true; });
        MotorControlReply reply{};
        reply.decision = variant == 4 ? MOTOR_RPC_ARMED : MOTOR_RPC_OK;
        if (variant == 2)
            reply.operation_id = 55;
        if (variant == 4 || variant == 5)
            reply.arm_token = 1;
        uint8_t payload[motor_rpc::replySize];
        motor_rpc::encodeReply(reply, payload);
        std::array<std::byte, 128> storage{};
        pw::rpc::internal::Packet packet(
            pw::rpc::internal::pwpb::PacketType::RESPONSE, 2, motor_rpc::service, motor_rpc::status,
            variant == 1 ? 124 : 123,
            pw::ConstByteSpan(reinterpret_cast<const std::byte *>(payload), sizeof(payload)),
            variant == 3 ? pw::Status::FailedPrecondition() : pw::OkStatus());
        auto encoded = packet.Encode(storage);
        assert(encoded.ok());
        CanRpcPacket frames{};
        frames.transaction = variant == 0 ? 124 : 123;
        frames.length = uint16_t(encoded->size());
        std::memcpy(frames.bytes, encoded->data(), encoded->size());
        for (size_t i = 0; i < CanRpc_FrameCount(frames.length); ++i) {
            uint8_t bytes[8];
            assert(CanRpc_EncodeFrame(&frames, i, bytes));
            c.receive(CAN_RPC_REPLY_ID, false, false, false, 8, bytes, 1000);
        }
        assert(c.state() ==
               (variant == 0 ? rpc_can::State::Waiting : rpc_can::State::ProtocolError));
    }
}
int main() {
    // Handler registration needs the same upstream Transfer worker as normal
    // firmware, even though these new calls are unary and do not read files.
    std::thread worker(PW_Rpc_CanTransferRun);
    assert(PW_CanRpc_Init());
    request(motor_rpc::status, MOTOR_RPC_OK);
    request(motor_rpc::arm, MOTOR_RPC_DISABLED);
    request(motor_rpc::start, MOTOR_RPC_DISABLED);
    request(motor_rpc::stop, MOTOR_RPC_DISABLED);
    assert(serviceCalls == 4);
    assert(!rpc_test_flash_calls && !rpc_test_ascii_calls);
    assert(readOnly.begin(rpc_readonly::ping, rpc_test_now));
    for (unsigned n = 0; readOnly.busy() && n < 1100; ++n)
        tick();
    assert(readOnly.state() == rpc_can::State::Success);
    uint8_t data[128];
    MotorControlRequest req{1, 1, 1, 1, 1};
    auto size = motor_rpc::encodeRequest(motor_rpc::start, 77, req, data, sizeof(data));
    rpc_readonly::Packet parsed;
    assert(rpc_readonly::decode(data, size, parsed));
    parsed.service_id = rpc_readonly::service;
    assert(!rpc_readonly::requestAllowed(parsed));
    data[1] = 2; // server-stream type cannot sneak into a unary actuator method
    assert(!PW_Rpc_CanProcess(30000, data, size));
    data[1] = 0;
    data[3] = 1;
    assert(!PW_Rpc_CanProcess(30001, data, size));
    data[3] = 2;
    data[size - 1] = 0;
    assert(!PW_Rpc_CanProcess(30002, data, size));
    size = motor_rpc::encodeRequest(motor_rpc::start, 77, req, data, sizeof(data));
    assert(rpc_readonly::decode(data, size, parsed));
    const auto payloadOffset = size_t(parsed.payload - data);
    data[payloadOffset] = 2;
    assert(!PW_Rpc_CanProcess(30003, data, size));
    data[payloadOffset] = 1;
    rpc_readonly::put32(data + payloadOffset + 4, 0);
    assert(!PW_Rpc_CanProcess(30004, data, size));
    assert(serviceCalls == 4); // Invalid requests cannot enter the business service.
    clientFaultTests();
    assert(!rpc_test_flash_calls && !rpc_test_ascii_calls);
    PW_Rpc_CanTransferStop();
    worker.join();
    puts("PASS: actual A/B official server + actual motor client through CAN queues; no hardware");
}
