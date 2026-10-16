#include "motor_control.h"
#include "motor_rpc_wire.h"
#include <array>
#include <cassert>
#include <cstdio>
struct Fixture {
    MotorControlView view{};
    MotorControlSession session{};
    unsigned starts = 0, stops = 0;
    bool reject = false;
    MotorControlPort port{this, snapshot, start, stop};
    static void snapshot(void *p, MotorControlView *v) {
        *v = static_cast<Fixture *>(p)->view;
    }
    static uint8_t start(void *p, uint32_t) {
        auto &f = *static_cast<Fixture *>(p);
        if (f.reject)
            return 0;
        ++f.starts;
        return 1;
    }
    static uint8_t stop(void *p, uint32_t) {
        ++static_cast<Fixture *>(p)->stops;
        return 1;
    }
    Fixture() {
        view.boot_id = 7;
        view.recipe_crc = 0x12345678;
    }
    MotorControlReply invoke(MotorControlOpcode op, MotorControlRequest r) {
        MotorControlReply out{};
        MotorControl_Dispatch(&session, &port, op, &r, &out);
        return out;
    }
    MotorControlRequest request(uint32_t id) {
        return {1, id, view.boot_id, view.recipe_crc, 0};
    }
    MotorControlRequest prepare(uint32_t id) {
        auto r = request(id);
        auto a = invoke(MOTOR_RPC_ARM, r);
        assert(a.decision == MOTOR_RPC_ARMED);
        r.arm_token = a.arm_token;
        return r;
    }
};
int main() {
    {
        Fixture f;
        f.view.blockers = MOTOR_BLOCK_REMOTE_DISABLED;
        for (auto op : {MOTOR_RPC_ARM, MOTOR_RPC_START, MOTOR_RPC_STOP})
            assert(f.invoke(op, f.request(1)).decision == MOTOR_RPC_DISABLED);
        assert(f.invoke(MOTOR_RPC_STATUS, f.request(0)).decision == MOTOR_RPC_OK);
        assert(!f.starts && !f.stops);
    }
    for (unsigned bit = 1; bit < 9; ++bit) {
        Fixture f;
        f.view.blockers = 1U << bit;
        assert(f.invoke(MOTOR_RPC_ARM, f.request(1)).decision == MOTOR_RPC_UNSAFE);
        assert(!f.starts);
    }
    {
        Fixture f;
        auto r = f.request(1);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_NOT_ARMED);
        r.boot_id = 8;
        assert(f.invoke(MOTOR_RPC_ARM, r).decision == MOTOR_RPC_BAD_SESSION);
        r = f.request(1);
        r.recipe_crc ^= 1;
        assert(f.invoke(MOTOR_RPC_ARM, r).decision == MOTOR_RPC_BAD_RECIPE);
        r = f.prepare(10);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_QUEUED);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_DUPLICATE && f.starts == 1);
        auto changed = r;
        changed.recipe_crc ^= 1;
        assert(f.invoke(MOTOR_RPC_START, changed).decision == MOTOR_RPC_REPLAY);
        r.operation_id = 9;
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_REPLAY);
        f.view.busy = 1;
        f.view.fault_reason = 1;
        f.view.preflight = 0xff;
        r = f.request(11);
        assert(f.invoke(MOTOR_RPC_STOP, r).decision == MOTOR_RPC_QUEUED);
        assert(f.invoke(MOTOR_RPC_STOP, r).decision == MOTOR_RPC_DUPLICATE && f.stops == 1);
    }
    {
        Fixture f;
        auto r = f.prepare(20);
        f.view.uptime_ms = MOTOR_CONTROL_ARM_MS;
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_EXPIRED && !f.starts);
        f.view.uptime_ms = 0xfffffff0U;
        r = f.prepare(21);
        f.view.uptime_ms = 0x20;
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_QUEUED && f.starts == 1);
    }
    {
        Fixture f;
        auto r = f.prepare(1);
        ++r.arm_token;
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_BAD_TOKEN);
        r = f.prepare(2);
        f.view.safe_latched = 1;
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_UNSAFE && !f.starts);
        f.view.safe_latched = 0;
        r = f.prepare(3);
        ++f.view.boot_id;
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_BAD_SESSION && !f.starts);
        r = f.prepare(4);
        f.reject = true;
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_QUEUE_REJECTED);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_NOT_ARMED && !f.starts);
    }
    {
        Fixture f;
        auto r = f.prepare(1);
        assert(f.invoke(MOTOR_RPC_ARM, r).decision == MOTOR_RPC_INVALID);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_NOT_ARMED && !f.starts);
        auto invalid = f.request(0);
        assert(f.invoke(MOTOR_RPC_START, invalid).decision == MOTOR_RPC_INVALID);
        invalid = f.request(1);
        invalid.version = 2;
        assert(f.invoke(MOTOR_RPC_ARM, invalid).decision == MOTOR_RPC_INVALID);
        f.view.boot_id = 0;
        invalid = f.request(1);
        assert(f.invoke(MOTOR_RPC_ARM, invalid).decision == MOTOR_RPC_BAD_SESSION);
    }
    {
        Fixture f;
        auto r = f.prepare(0xffffffffU);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_QUEUED);
        r = f.prepare(1);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_QUEUED);
        r = f.prepare(0x80000001U);
        assert(f.invoke(MOTOR_RPC_START, r).decision == MOTOR_RPC_REPLAY);
    }
    {
        std::array<uint8_t, 128> bytes{};
        rpc_readonly::Packet p;
        MotorControlRequest r{1, 55, 7, 0x12345678, 9};
        for (auto method : {motor_rpc::arm, motor_rpc::start, motor_rpc::stop, motor_rpc::status}) {
            auto size = motor_rpc::encodeRequest(method, 1, r, bytes.data(), bytes.size());
            assert(size && rpc_readonly::decode(bytes.data(), size, p) &&
                   motor_rpc::requestAllowed(p));
            assert(!rpc_readonly::requestAllowed(p)); // original whitelist is NOT widened
            p.channel_id = 1;
            assert(!motor_rpc::requestAllowed(p));
        }
        assert(!motor_rpc::encodeRequest(0, 1, r, bytes.data(), bytes.size()));
        assert(!motor_rpc::encodeRequest(motor_rpc::start, 0, r, bytes.data(), bytes.size()));
        r.version = 2;
        assert(!motor_rpc::encodeRequest(motor_rpc::start, 1, r, bytes.data(), bytes.size()));
        Fixture f;
        auto out = f.invoke(MOTOR_RPC_STATUS, f.request(0));
        motor_rpc::encodeReply(out, bytes.data());
        MotorControlReply decoded{};
        assert(motor_rpc::decodeReply(bytes.data(), motor_rpc::replySize, decoded));
        assert(!motor_rpc::decodeReply(bytes.data(), motor_rpc::replySize - 1, decoded));
    }
    std::puts("PASS: simulated admission/replay/timeout and wire tests; no hardware connected");
}
