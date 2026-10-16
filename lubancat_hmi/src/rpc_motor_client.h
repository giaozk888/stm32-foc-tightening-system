#ifndef RPC_MOTOR_CLIENT_H
#define RPC_MOTOR_CLIENT_H
#include "motor_rpc_wire.h"
#include "rpc_can_client.h"

namespace rpc_can {
/* Same bounded CAN framing, independent business service. No automatic
 * retry of ARM/START/STOP and no actuator authorization from a UI checkbox. */
class MotorClient {
  public:
    explicit MotorClient(uint32_t seed = 1) : nextCall_(seed ? seed : 1) {
        CanRpc_Reset(&rx_);
    }
    bool begin(uint32_t method, int64_t now,
               const MotorControlRequest &request = MotorControlRequest{MOTOR_CONTROL_VERSION, 0, 0,
                                                                        0, 0}) {
        if (busy() || !motor_rpc::opcode(method))
            return false;
        const uint32_t call = nextCall_++;
        if (!nextCall_)
            nextCall_ = 1;
        tx_.length =
            uint16_t(motor_rpc::encodeRequest(method, call, request, tx_.bytes, sizeof(tx_.bytes)));
        if (!tx_.length)
            return false;
        tx_.transaction = uint16_t((call - 1) % 0x7fff + 1);
        method_ = method;
        call_ = call;
        operation_ = method == motor_rpc::status ? 0 : request.operation_id;
        CanRpc_Reset(&rx_);
        reply_ = {};
        remoteStatus_ = 0;
        frame_ = 0;
        started_ = nextSend_ = now;
        state_ = State::Sending;
        return true;
    }
    void tick(int64_t now, const std::function<bool(const uint8_t *)> &send) {
        if (!busy())
            return;
        if (now - started_ >= 5000) {
            state_ = State::Timeout;
            CanRpc_Reset(&rx_);
            return;
        }
        if (CanRpc_Expire(&rx_, uint32_t(now))) {
            state_ = State::ProtocolError;
            return;
        }
        if (state_ != State::Sending || now < nextSend_)
            return;
        uint8_t bytes[8];
        if (!CanRpc_EncodeFrame(&tx_, frame_, bytes) || !send(bytes)) {
            state_ = State::SendError;
            return;
        }
        ++frame_;
        nextSend_ = now + 75;
        if (frame_ == CanRpc_FrameCount(tx_.length))
            state_ = State::Waiting;
    }
    void receive(uint32_t id, bool extended, bool remote, bool error, uint8_t length,
                 const uint8_t *bytes, int64_t now) {
        if (state_ != State::Waiting || id != CAN_RPC_REPLY_ID || !bytes || length != 8 ||
            extended || remote || error ||
            uint16_t(bytes[1] | uint16_t(bytes[2]) << 8) != tx_.transaction)
            return;
        if (now - started_ >= 5000) {
            state_ = State::Timeout;
            return;
        }
        auto result =
            CanRpc_Feed(&rx_, CAN_RPC_REPLY_ID, id, 0, 0, 0, 0, length, bytes, uint32_t(now));
        if (result == CAN_RPC_INVALID || result == CAN_RPC_BAD_CRC || result == CAN_RPC_TIMED_OUT) {
            state_ = State::ProtocolError;
            return;
        }
        if (result != CAN_RPC_COMPLETE)
            return;
        rpc_readonly::Packet p;
        if (!rpc_readonly::decode(rx_.packet.bytes, rx_.packet.length, p) || p.type != 1 ||
            p.channel_id != rpc_readonly::channel || p.service_id != motor_rpc::service ||
            p.method_id != method_ || p.call_id != call_ ||
            !motor_rpc::decodeReply(p.payload, p.payload_size, reply_) ||
            reply_.operation_id != operation_) {
            state_ = State::ProtocolError;
            return;
        }
        remoteStatus_ = p.status;
        const bool accepted = reply_.decision <= MOTOR_RPC_DUPLICATE;
        // OK is not enough: validate both application decision and RPC status.
        if ((accepted && p.status != 0) || (!accepted && p.status != 9)) {
            state_ = State::ProtocolError;
            return;
        }
        const bool armed = reply_.decision == MOTOR_RPC_ARMED;
        const bool queued =
            reply_.decision == MOTOR_RPC_QUEUED || reply_.decision == MOTOR_RPC_DUPLICATE;
        if ((method_ == motor_rpc::status && reply_.decision != MOTOR_RPC_OK) ||
            (method_ != motor_rpc::status && reply_.decision == MOTOR_RPC_OK) ||
            (armed && (method_ != motor_rpc::arm || !reply_.arm_token)) ||
            (queued && method_ == motor_rpc::arm) || (!armed && reply_.arm_token)) {
            state_ = State::ProtocolError;
            return;
        }
        state_ = State::Success; // Complete valid reply; may contain a REJECTION.
    }
    bool busy() const {
        return state_ == State::Sending || state_ == State::Waiting;
    }
    State state() const {
        return state_;
    }
    uint32_t call() const {
        return call_;
    }
    uint32_t remoteStatus() const {
        return remoteStatus_;
    }
    const MotorControlReply &reply() const {
        return reply_;
    }

  private:
    CanRpcPacket tx_{};
    CanRpcReceiver rx_{};
    MotorControlReply reply_{};
    uint32_t nextCall_, call_ = 0, method_ = 0, operation_ = 0, remoteStatus_ = 0;
    size_t frame_ = 0;
    int64_t started_ = 0, nextSend_ = 0;
    State state_ = State::Idle;
};
} // namespace rpc_can
#endif
