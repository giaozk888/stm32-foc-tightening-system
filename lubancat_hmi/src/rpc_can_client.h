#ifndef RPC_CAN_CLIENT_H
#define RPC_CAN_CLIENT_H
#include "rpc_readonly_wire.h"
#include <array>
#include <algorithm>
#include <functional>

namespace rpc_can {
enum class State { Idle, Sending, Waiting, Success, Timeout, SendError, ProtocolError };
class Client {
 public:
    explicit Client(std::uint32_t seed = 1U) : nextCall_(seed ? seed : 1U) { CanRpc_Reset(&rx_); }
    bool begin(std::uint32_t method, std::int64_t now, const std::uint8_t *payload = nullptr, std::size_t length = 0) {
        if (busy() || !rpc_readonly::allowed(method)) return false;
        method_ = method; call_ = nextCall_++; if (!nextCall_) nextCall_ = 1U;
        tx_.transaction = static_cast<std::uint16_t>((call_ - 1U) % 0x7fffU + 1U);
        rpc_readonly::put32(nonce_.data(), call_);
        tx_.length = static_cast<std::uint16_t>(rpc_readonly::encodeRequest(method, call_,
            method == rpc_readonly::ping ? nonce_.data() : payload,
            method == rpc_readonly::ping ? nonce_.size() : length, tx_.bytes, sizeof(tx_.bytes)));
        if (!tx_.length) return false;
        CanRpc_Reset(&rx_); frame_ = 0; started_ = now; nextSend_ = now;
        resultSize_ = 0; remoteStatus_ = 0; state_ = State::Sending; return true;
    }
    void tick(std::int64_t now, const std::function<bool(const std::uint8_t *)>& send) {
        if (!busy()) return;
        if (now - started_ >= 5000) { state_ = State::Timeout; CanRpc_Reset(&rx_); return; }
        if (CanRpc_Expire(&rx_, static_cast<std::uint32_t>(now))) { state_ = State::ProtocolError; return; }
        if (state_ != State::Sending || now < nextSend_) return;
        std::uint8_t bytes[8];
        if (!CanRpc_EncodeFrame(&tx_, frame_, bytes) || !send(bytes)) { state_ = State::SendError; return; }
        ++frame_; nextSend_ = now + 75; // <= two frames per 100 ms, three-entry MCU RX FIFO.
        if (frame_ == CanRpc_FrameCount(tx_.length)) state_ = State::Waiting;
    }
    void receive(std::uint32_t id, bool extended, bool remote, bool error,
                 std::uint8_t length, const std::uint8_t *bytes, std::int64_t now) {
        if (state_ != State::Waiting || id != CAN_RPC_REPLY_ID) return;
        if (now - started_ >= 5000) { state_ = State::Timeout; return; }
        // Unrelated transactions must not occupy this client's reassembly slot.
        if (!bytes || length != 8 || extended || remote || error) return;
        const auto transaction = std::uint16_t(bytes[1] | (std::uint16_t(bytes[2]) << 8));
        if (transaction != tx_.transaction) return;
        const auto result = CanRpc_Feed(&rx_, CAN_RPC_REPLY_ID, id, extended, remote, error, 0U, length, bytes,
                                       static_cast<std::uint32_t>(now));
        if (result == CAN_RPC_INVALID || result == CAN_RPC_BAD_CRC || result == CAN_RPC_TIMED_OUT) {
            state_ = State::ProtocolError; return;
        }
        if (result != CAN_RPC_COMPLETE) return;
        rpc_readonly::Packet packet;
        if (!rpc_readonly::decode(rx_.packet.bytes, rx_.packet.length, packet) ||
            packet.channel_id != rpc_readonly::channel || packet.service_id != rpc_readonly::service ||
            packet.method_id != method_ || packet.call_id != call_ ||
            (packet.type != 1U && packet.type != 5U)) { state_ = State::ProtocolError; return; }
        remoteStatus_ = packet.status;
        if (packet.status != 0U || packet.type != 1U) { state_ = State::ProtocolError; return; }
        const std::size_t expected = method_ == rpc_readonly::ping ? nonce_.size() :
            method_ == rpc_readonly::status ? RPC_READONLY_STATUS_WORDS * 4U :
            method_ == rpc_readonly::params ? RPC_READONLY_PARAMS_WORDS * 4U : RPC_READONLY_DIAG_WORDS * 4U;
        if (packet.payload_size != expected ||
            (method_ == rpc_readonly::ping ? std::memcmp(packet.payload, nonce_.data(), nonce_.size()) != 0 :
                                           rpc_readonly::get32(packet.payload) != RPC_READONLY_VERSION)) {
            state_ = State::ProtocolError; return;
        }
        std::copy_n(packet.payload, expected, result_.begin()); resultSize_ = expected; state_ = State::Success;
    }
    bool busy() const { return state_ == State::Sending || state_ == State::Waiting; }
    State state() const { return state_; }
    std::uint32_t method() const { return method_; }
    std::uint32_t call() const { return call_; }
    std::uint16_t transaction() const { return tx_.transaction; }
    std::uint32_t remoteStatus() const { return remoteStatus_; }
    std::size_t resultSize() const { return resultSize_; }
    const std::uint8_t *result() const { return result_.data(); }
 private:
    CanRpcPacket tx_{};
    CanRpcReceiver rx_{};
    std::array<std::uint8_t, 4> nonce_{};
    std::array<std::uint8_t, RPC_READONLY_PAYLOAD_MAX> result_{};
    std::uint32_t nextCall_, method_ = 0, call_ = 0, remoteStatus_ = 0;
    std::int64_t started_ = 0, nextSend_ = 0;
    std::size_t frame_ = 0, resultSize_ = 0;
    State state_ = State::Idle;
};
}
#endif
