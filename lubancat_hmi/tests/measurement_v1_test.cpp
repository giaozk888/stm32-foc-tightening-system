#include "measurement_v1.h"

#include <array>
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main()
{
    std::array<std::uint8_t, 8> motor{{0x39, 0x30, 0, 0, 0x06, 0xff, 0xfe, 0xff}};
    measurement_v1::MotorPacket m;
    assert(measurement_v1::decodeMotor(0x181, false, false, false, 8, motor.data(), m));
    assert(m.angleValid() && m.angleMdeg == 12345);
    assert(m.currentValid() && m.iqMa == -250 && m.sequence == 0xfffe);
    assert(!measurement_v1::decodeMotor(0x180, false, false, false, 8, motor.data(), m));
    assert(!measurement_v1::decodeMotor(0x181, true, false, false, 8, motor.data(), m));
    assert(!measurement_v1::decodeMotor(0x181, false, true, false, 8, motor.data(), m));
    assert(!measurement_v1::decodeMotor(0x181, false, false, true, 8, motor.data(), m));
    assert(!measurement_v1::decodeMotor(0x181, false, false, false, 7, motor.data(), m));
    motor = {{0, 0, 0, 0x80, 0, 0x80, 0xff, 0xff}};
    assert(measurement_v1::decodeMotor(0x181, false, false, false, 8, motor.data(), m));
    assert(!m.angleValid() && !m.currentValid());

    std::array<std::uint8_t, 8> electrical{{0xc0, 0x5d, 0x85, 0xff, 0x34, 0x12, 3, 1}};
    measurement_v1::ElectricalPacket e;
    assert(measurement_v1::decodeElectrical(0x182, false, false, false, 8,
                                            electrical.data(), e));
    assert(e.vbusValid && e.vbusMv == 24000);
    assert(e.speedValid && e.speedDeciRpm == -123 && e.sequence == 0x1234);
    electrical[7] = 2;
    assert(!measurement_v1::decodeElectrical(0x182, false, false, false, 8,
                                             electrical.data(), e));
    electrical[7] = 1;
    electrical[6] = 0;
    assert(!measurement_v1::decodeElectrical(0x182, false, false, false, 8,
                                             electrical.data(), e));
    electrical = {{0, 0, 0, 0, 0x35, 0x12, 0, 1}};
    assert(measurement_v1::decodeElectrical(0x182, false, false, false, 8,
                                            electrical.data(), e));
    assert(!e.vbusValid && !e.speedValid);

    measurement_v1::Tracker<measurement_v1::MotorPacket> tracker;
    m.sequence = 0xffff;
    assert(tracker.accept(m, 100));
    m.sequence = 0;
    assert(tracker.accept(m, 200));
    assert(!tracker.accept(m, 300));
    assert(tracker.fresh(700) && !tracker.fresh(701));
    m.sequence = 100;
    assert(tracker.accept(m, 800));
    m.sequence = 99;
    assert(!tracker.accept(m, 900));
    assert(tracker.accept(m, 1301));
    tracker.reset();
    assert(!tracker.seen() && !tracker.fresh(1301));
    m.sequence = 0;
    assert(tracker.accept(m, 1302));
    return 0;
}
