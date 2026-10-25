#ifndef MOTOR_RPC_WIRE_H
#define MOTOR_RPC_WIRE_H
#include "motor_control.h"
#include "rpc_readonly_wire.h"

namespace motor_rpc {
constexpr uint32_t service = rpc_readonly::hash("foc.MotorControl");
constexpr uint32_t arm = rpc_readonly::hash("Arm");
constexpr uint32_t start = rpc_readonly::hash("StartTightening");
constexpr uint32_t stop = rpc_readonly::hash("Stop");
constexpr uint32_t status = rpc_readonly::hash("GetOperationStatus");
constexpr size_t requestSize = MOTOR_CONTROL_REQUEST_WORDS * 4U;
constexpr size_t replySize = MOTOR_CONTROL_REPLY_WORDS * 4U;
inline MotorControlOpcode opcode(uint32_t method) {
    return method == arm      ? MOTOR_RPC_ARM
           : method == start  ? MOTOR_RPC_START
           : method == stop   ? MOTOR_RPC_STOP
           : method == status ? MOTOR_RPC_STATUS
                              : MotorControlOpcode(0);
}
inline bool requestAllowed(const rpc_readonly::Packet &p) {
    return p.type == 0 && p.status == 0 && p.channel_id == rpc_readonly::channel &&
           p.service_id == service && p.call_id && opcode(p.method_id) &&
           (p.method_id == status ? p.payload_size == 0
                                  : p.payload_size == requestSize && p.payload &&
                                        rpc_readonly::get32(p.payload) == MOTOR_CONTROL_VERSION &&
                                        rpc_readonly::get32(p.payload + 4) != 0);
}
inline MotorControlRequest request(const rpc_readonly::Packet &p) {
    MotorControlRequest r{MOTOR_CONTROL_VERSION, 0, 0, 0, 0};
    if (p.payload_size == requestSize && p.payload) {
        r.version = rpc_readonly::get32(p.payload);
        r.operation_id = rpc_readonly::get32(p.payload + 4);
        r.boot_id = rpc_readonly::get32(p.payload + 8);
        r.recipe_crc = rpc_readonly::get32(p.payload + 12);
        r.arm_token = rpc_readonly::get32(p.payload + 16);
    }
    return r;
}
inline void encodeReply(const MotorControlReply &r, uint8_t *bytes) {
    const uint32_t words[MOTOR_CONTROL_REPLY_WORDS] = {
        MOTOR_CONTROL_VERSION, r.decision,          r.view.blockers, r.view.preflight,
        r.view.boot_id,        r.view.recipe_crc,   r.arm_token,     r.operation_id,
        r.view.job_id,         r.view.job_state,    r.view.mode,     r.view.busy,
        r.view.fault_reason,   r.view.safe_latched, r.view.uptime_ms};
    for (size_t i = 0; i < MOTOR_CONTROL_REPLY_WORDS; ++i)
        rpc_readonly::put32(bytes + i * 4, words[i]);
}
inline bool decodeReply(const uint8_t *b, size_t size, MotorControlReply &out) {
    if (!b || size != replySize || rpc_readonly::get32(b) != MOTOR_CONTROL_VERSION)
        return false;
    MotorControlReply r{};
    r.decision = rpc_readonly::get32(b + 4);
    r.view.blockers = rpc_readonly::get32(b + 8);
    r.view.preflight = rpc_readonly::get32(b + 12);
    r.view.boot_id = rpc_readonly::get32(b + 16);
    r.view.recipe_crc = rpc_readonly::get32(b + 20);
    r.arm_token = rpc_readonly::get32(b + 24);
    r.operation_id = rpc_readonly::get32(b + 28);
    r.view.job_id = rpc_readonly::get32(b + 32);
    r.view.job_state = rpc_readonly::get32(b + 36);
    r.view.mode = rpc_readonly::get32(b + 40);
    r.view.busy = rpc_readonly::get32(b + 44);
    r.view.fault_reason = rpc_readonly::get32(b + 48);
    r.view.safe_latched = rpc_readonly::get32(b + 52);
    r.view.uptime_ms = rpc_readonly::get32(b + 56);
    if (r.decision > MOTOR_RPC_INVALID || r.view.job_state > MOTOR_JOB_FAULT || r.view.busy > 1 ||
        r.view.safe_latched > 1)
        return false;
    out = r;
    return true;
}
inline size_t encodeRequest(uint32_t method, uint32_t call, const MotorControlRequest &r,
                            uint8_t *out, size_t capacity) {
    const auto op = opcode(method);
    if (!op || !call || !out ||
        (op != MOTOR_RPC_STATUS && (r.version != MOTOR_CONTROL_VERSION || !r.operation_id)))
        return 0;
    const size_t length = op == MOTOR_RPC_STATUS ? 0 : requestSize;
    if (capacity < 23 + length)
        return 0;
    size_t pos = 0;
    out[pos++] = 0x08;
    out[pos++] = 0;
    out[pos++] = 0x10;
    out[pos++] = rpc_readonly::channel;
    out[pos++] = 0x1d;
    rpc_readonly::put32(out + pos, service);
    pos += 4;
    out[pos++] = 0x25;
    rpc_readonly::put32(out + pos, method);
    pos += 4;
    if (length) {
        out[pos++] = 0x2a;
        out[pos++] = uint8_t(length);
        const uint32_t words[5] = {r.version, r.operation_id, r.boot_id, r.recipe_crc, r.arm_token};
        for (auto word : words) {
            rpc_readonly::put32(out + pos, word);
            pos += 4;
        }
    }
    out[pos++] = 0x38;
    do {
        out[pos++] = uint8_t((call & 0x7f) | (call > 127 ? 0x80 : 0));
        call >>= 7;
    } while (call);
    return pos;
}
} // namespace motor_rpc
#endif
