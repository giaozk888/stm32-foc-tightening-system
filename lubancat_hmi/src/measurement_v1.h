#pragma once

#include <cstdint>
#include <limits>

namespace measurement_v1 {

constexpr std::uint32_t kMotorId = 0x181U;
constexpr std::uint32_t kElectricalId = 0x182U;
constexpr std::uint8_t kLength = 8U;
constexpr int kFreshMs = 500;

struct MotorPacket {
    std::int32_t angleMdeg = std::numeric_limits<std::int32_t>::min();
    std::int16_t iqMa = std::numeric_limits<std::int16_t>::min();
    std::uint16_t sequence = 0;
    bool angleValid() const { return angleMdeg != std::numeric_limits<std::int32_t>::min(); }
    bool currentValid() const { return iqMa != std::numeric_limits<std::int16_t>::min(); }
};

struct ElectricalPacket {
    std::uint16_t vbusMv = 0;
    std::int16_t speedDeciRpm = 0;
    std::uint16_t sequence = 0;
    bool vbusValid = false;
    bool speedValid = false;
};

inline bool decodeMotor(std::uint32_t id, bool extended, bool remote, bool error,
                        std::uint8_t length, const std::uint8_t *data, MotorPacket &out)
{
    if (id != kMotorId || extended || remote || error || length != kLength || !data)
        return false;
    const std::uint32_t rawAngle = std::uint32_t(data[0]) |
        (std::uint32_t(data[1]) << 8) | (std::uint32_t(data[2]) << 16) |
        (std::uint32_t(data[3]) << 24);
    const std::uint16_t rawIq = std::uint16_t(data[4]) |
        (std::uint16_t(data[5]) << 8);
    // The wire protocol uses two's-complement signed values.
    out.angleMdeg = rawAngle <= INT32_MAX ? std::int32_t(rawAngle) :
        std::int32_t(std::int64_t(rawAngle) - (std::int64_t(1) << 32));
    out.iqMa = rawIq <= INT16_MAX ? std::int16_t(rawIq) :
        std::int16_t(std::int32_t(rawIq) - (1 << 16));
    out.sequence = std::uint16_t(data[6]) | (std::uint16_t(data[7]) << 8);
    return true;
}

inline bool decodeElectrical(std::uint32_t id, bool extended, bool remote, bool error,
                             std::uint8_t length, const std::uint8_t *data,
                             ElectricalPacket &out)
{
    if (id != kElectricalId || extended || remote || error || length != kLength || !data ||
        data[7] != 1U || (data[6] & ~0x03U) != 0U)
        return false;
    const std::uint16_t rawSpeed = std::uint16_t(data[2]) |
        (std::uint16_t(data[3]) << 8);
    out.vbusMv = std::uint16_t(data[0]) | (std::uint16_t(data[1]) << 8);
    out.speedDeciRpm = rawSpeed <= INT16_MAX ? std::int16_t(rawSpeed) :
        std::int16_t(std::int32_t(rawSpeed) - (1 << 16));
    out.sequence = std::uint16_t(data[4]) | (std::uint16_t(data[5]) << 8);
    out.vbusValid = (data[6] & 0x01U) != 0U;
    out.speedValid = (data[6] & 0x02U) != 0U;
    if ((!out.vbusValid && out.vbusMv != 0U) ||
        (!out.speedValid && out.speedDeciRpm != 0)) return false;
    return true;
}

inline bool sequenceForward(std::uint16_t current, std::uint16_t previous)
{
    const auto delta = std::uint16_t(current - previous);
    return delta != 0U && delta < 0x8000U;
}

template <typename Packet> class Tracker {
public:
    bool accept(const Packet &candidate, std::int64_t nowMs)
    {
        if (fresh(nowMs) && !sequenceForward(candidate.sequence, packet_.sequence)) return false;
        packet_ = candidate;
        lastAcceptedMs_ = nowMs;
        seen_ = true;
        return true;
    }
    bool seen() const { return seen_; }
    void reset()
    {
        packet_ = Packet{};
        lastAcceptedMs_ = 0;
        seen_ = false;
    }
    bool fresh(std::int64_t nowMs) const
    {
        return seen_ && nowMs >= lastAcceptedMs_ && nowMs - lastAcceptedMs_ <= kFreshMs;
    }
    const Packet &packet() const { return packet_; }
private:
    Packet packet_{};
    std::int64_t lastAcceptedMs_ = 0;
    bool seen_ = false;
};

}  // namespace measurement_v1
