#include "preflight_observation.h"

#include <cassert>

using preflight_observation::State;

int main()
{
    preflight_observation::Input in;
    auto result = preflight_observation::evaluate(in);
    assert(result.status == State::Unknown);
    assert(result.idle == State::Unknown);
    assert(result.angle == State::Unknown);

    in.statusFresh = true;
    in.status.sequence = 42;
    in.status.flags = 0x04;
    in.motorFresh = true;
    in.motor.sequence = 42;
    in.motor.angleMdeg = 1200;
    in.electricalFresh = true;
    in.electrical.sequence = 42;
    in.electrical.speedValid = true;
    in.electrical.vbusValid = true;
    result = preflight_observation::evaluate(in);
    assert(result.status == State::Observed);
    assert(result.idle == State::Observed);
    assert(result.softwareFaultClear == State::Observed);
    assert(result.encoderFlag == State::Observed);
    assert(result.angle == State::Observed);
    assert(result.speed == State::Observed);
    assert(result.vbusEstimate == State::Observed);
    assert(result.sdOutputLow == State::Observed);

    in.motor.sequence = 41;
    in.electrical.sequence = 41;
    result = preflight_observation::evaluate(in);
    assert(result.angle == State::Unknown);
    assert(result.speed == State::Unknown);
    assert(result.vbusEstimate == State::Unknown);

    in.motor.sequence = 42;
    in.electrical.sequence = 42;
    in.status.mode = 2;
    in.status.flags = 0x0a;
    in.status.fault = 7;
    in.motor.angleMdeg = INT32_MIN;
    in.electrical.speedValid = false;
    in.electrical.vbusValid = false;
    result = preflight_observation::evaluate(in);
    assert(result.idle == State::Attention);
    assert(result.softwareFaultClear == State::Attention);
    assert(result.encoderFlag == State::Attention);
    assert(result.sdOutputLow == State::Attention);
    assert(result.angle == State::Attention);
    assert(result.speed == State::Attention);
    assert(result.vbusEstimate == State::Attention);

    in.statusFresh = false;
    result = preflight_observation::evaluate(in);
    assert(result.status == State::Unknown);
    assert(result.softwareFaultClear == State::Unknown);
    assert(result.sdOutputLow == State::Unknown);
}
