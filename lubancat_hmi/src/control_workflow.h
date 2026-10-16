#pragma once

#include "can_control_v0.h"
#include "measurement_v1.h"
#include "status_v1.h"

#include <array>
#include <cstdint>

namespace control_workflow {

// These are independent requirements, not permissions inferred from CAN
// telemetry. Unknown/unwired inputs stay false and keep START locked.
struct Evidence {
    bool canUp = false;
    bool statusFresh = false;
    bool motorFresh = false;
    bool electricalFresh = false;
    status_v1::Packet status{};
    measurement_v1::MotorPacket motor{};
    measurement_v1::ElectricalPacket electrical{};
    bool firmwareControlVerified = false;
    bool estopFeedbackReleased = false;
    bool powerStageFeedbackReady = false;
    bool recipeVerified = false;
    // Independent acceptance evidence; estimated vbus and FOC flags cannot set this.
    bool sensingVerified = false;
};

enum Missing : std::uint32_t {
    CanLink = 1U << 0,
    FreshTelemetry = 1U << 1,
    IdleAndStationary = 1U << 2,
    SoftwareHealthy = 1U << 3,
    FirmwareControl = 1U << 4,
    EstopFeedback = 1U << 5,
    PowerFeedback = 1U << 6,
    VerifiedRecipe = 1U << 7,
    VerifiedSensing = 1U << 8,
};

inline std::uint32_t missing(const Evidence &in)
{
    std::uint32_t result = 0;
    if (!in.canUp) result |= CanLink;
    const bool paired = in.statusFresh && in.motorFresh && in.electricalFresh &&
        in.motor.sequence == in.status.sequence &&
        in.electrical.sequence == in.status.sequence &&
        in.motor.angleValid() && in.electrical.speedValid &&
        in.electrical.vbusValid;
    if (!paired) result |= FreshTelemetry;
    if (!in.statusFresh || in.status.mode != 0U || !paired ||
        in.electrical.speedDeciRpm < -20 || in.electrical.speedDeciRpm > 20)
        result |= IdleAndStationary;
    if (!in.statusFresh || in.status.fault != 0U ||
        (in.status.flags & 0x0FU) != 0x0DU)
        result |= SoftwareHealthy; // FOC, encoder, driver output; no fault.
    if (!in.firmwareControlVerified) result |= FirmwareControl;
    if (!in.estopFeedbackReleased) result |= EstopFeedback;
    if (!in.powerStageFeedbackReady) result |= PowerFeedback;
    if (!in.recipeVerified) result |= VerifiedRecipe;
    if (!in.sensingVerified) result |= VerifiedSensing;
    return result;
}

enum class Phase {
    Locked, AwaitingReply, IntentAccepted, Rejected, TimedOut,
    RunningObserved, IdleObserved, LinkLost
};

// A CAN ACK is only an intent acknowledgement. Telemetry is a separate,
// uncorrelated observation until the firmware publishes a cycle request ID.
class Transaction {
public:
    bool begin(const CanControlV0_Request &request, std::int64_t nowMs,
               std::uint16_t statusSequence, std::uint32_t missingMask,
               std::array<std::uint8_t, 8> &encoded)
    {
        const bool stop = request.opcode == CAN_CONTROL_V0_STOP;
        if ((phase_ == Phase::AwaitingReply && !stop) ||
            (stop ? (missingMask & FirmwareControl) != 0U
                  : missingMask != 0U || request.session_token == 0U) ||
            CanControlV0_EncodeRequest(&request, encoded.data()) == 0U)
            return false;
        request_ = request;
        startMs_ = nowMs;
        statusSequence_ = statusSequence;
        phase_ = Phase::AwaitingReply;
        stopRecommended_ = false;
        return true;
    }

    bool accept(const CanControlV0_Reply &reply, std::int64_t nowMs)
    {
        if (phase_ != Phase::AwaitingReply || nowMs < startMs_ ||
            nowMs - startMs_ > 500 || reply.opcode != request_.opcode ||
            reply.sequence != request_.sequence ||
            reply.session_token != request_.session_token)
            return false;
        const auto expected = request_.opcode == CAN_CONTROL_V0_ARM
            ? CAN_CONTROL_V0_ARMED
            : request_.opcode == CAN_CONTROL_V0_START
                ? CAN_CONTROL_V0_START_INTENT : CAN_CONTROL_V0_STOP_INTENT;
        phase_ = reply.decision == expected ? Phase::IntentAccepted : Phase::Rejected;
        decision_ = reply.decision;
        return true;
    }

    void observe(const status_v1::Packet &status, bool fresh)
    {
        if (phase_ != Phase::IntentAccepted || !fresh ||
            !status_v1::sequenceForward(status.sequence, statusSequence_) ||
            status.fault != 0U || (status.flags & 0x02U) != 0U)
            return;
        if (request_.opcode == CAN_CONTROL_V0_START && status.mode != 0U)
            phase_ = Phase::RunningObserved;
        else if (request_.opcode == CAN_CONTROL_V0_STOP && status.mode == 0U)
            phase_ = Phase::IdleObserved;
    }

    void tick(std::int64_t nowMs, bool telemetryFresh = true)
    {
        const bool actionPending = request_.opcode != CAN_CONTROL_V0_ARM &&
            (phase_ == Phase::IntentAccepted || phase_ == Phase::RunningObserved);
        if (actionPending && !telemetryFresh) {
            phase_ = Phase::LinkLost;
            stopRecommended_ = request_.opcode == CAN_CONTROL_V0_START;
        } else if (phase_ == Phase::AwaitingReply && nowMs - startMs_ > 500) {
            phase_ = Phase::TimedOut;
            stopRecommended_ = request_.opcode == CAN_CONTROL_V0_START;
        } else if (phase_ == Phase::IntentAccepted && actionPending &&
                   nowMs - startMs_ > 1500) {
            phase_ = Phase::TimedOut;
            stopRecommended_ = request_.opcode == CAN_CONTROL_V0_START;
        }
    }

    void lock() { phase_ = Phase::Locked; }
    Phase phase() const { return phase_; }
    std::uint8_t decision() const { return decision_; }
    bool stopRecommended() const { return stopRecommended_; }

private:
    Phase phase_ = Phase::Locked;
    CanControlV0_Request request_{};
    std::int64_t startMs_ = 0;
    std::uint16_t statusSequence_ = 0;
    std::uint8_t decision_ = 0;
    bool stopRecommended_ = false;
};

} // namespace control_workflow
