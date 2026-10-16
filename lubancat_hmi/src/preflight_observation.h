#pragma once

#include "measurement_v1.h"
#include "status_v1.h"

namespace preflight_observation {

// These are observations from read-only CAN telemetry, not safety approvals.
enum class State { Unknown, Observed, Attention };

struct Input {
    bool statusFresh = false;
    bool motorFresh = false;
    bool electricalFresh = false;
    status_v1::Packet status{};
    measurement_v1::MotorPacket motor{};
    measurement_v1::ElectricalPacket electrical{};
};

struct Result {
    State status = State::Unknown;
    State idle = State::Unknown;
    State softwareFaultClear = State::Unknown;
    State encoderFlag = State::Unknown;
    State angle = State::Unknown;
    State speed = State::Unknown;
    State vbusEstimate = State::Unknown;
    State sdOutputLow = State::Unknown;
};

inline Result evaluate(const Input &in)
{
    Result out;
    if (!in.statusFresh) return out;
    out.status = State::Observed;
    out.idle = in.status.mode == 0 ? State::Observed : State::Attention;
    out.softwareFaultClear =
        (in.status.flags & 0x02U) == 0U && in.status.fault == 0U
            ? State::Observed : State::Attention;
    out.encoderFlag = (in.status.flags & 0x04U) != 0U
        ? State::Observed : State::Attention;
    // SD is the MCU's output flag, never a power-stage or e-stop feedback.
    out.sdOutputLow = (in.status.flags & 0x08U) == 0U
        ? State::Observed : State::Attention;

    if (in.motorFresh && in.motor.sequence == in.status.sequence) {
        out.angle = in.motor.angleValid() ? State::Observed : State::Attention;
    }
    if (in.electricalFresh && in.electrical.sequence == in.status.sequence) {
        out.speed = in.electrical.speedValid ? State::Observed : State::Attention;
        out.vbusEstimate = in.electrical.vbusValid ? State::Observed : State::Attention;
    }
    return out;
}

}  // namespace preflight_observation
