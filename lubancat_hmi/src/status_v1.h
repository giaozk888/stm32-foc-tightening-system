#pragma once

#include <cstdint>

namespace status_v1 {

constexpr std::uint32_t kId = 0x180U;
constexpr std::uint8_t kVersion = 1U;
constexpr std::uint8_t kLength = 8U;
constexpr std::uint8_t kKnownFlags = 0x0FU;
constexpr int kFreshMs = 500;

struct Packet {
    std::uint8_t mode = 0;
    std::uint8_t flags = 0;
    std::uint16_t fault = 0;
    std::uint16_t sequence = 0;
};

inline bool decode(std::uint32_t id, bool extended, bool remote, bool error,
                   std::uint8_t length, const std::uint8_t *data, Packet &out)
{
    if (id != kId || extended || remote || error || length != kLength || !data ||
        data[0] != kVersion || data[1] > 3U ||
        (data[2] & ~kKnownFlags) != 0U || data[7] != 0U) {
        return false;
    }
    out.mode = data[1];
    out.flags = data[2];
    out.fault = static_cast<std::uint16_t>(data[3] | (data[4] << 8));
    out.sequence = static_cast<std::uint16_t>(data[5] | (data[6] << 8));
    return true;
}

inline bool sequenceForward(std::uint16_t current, std::uint16_t previous)
{
    const auto delta = static_cast<std::uint16_t>(current - previous);
    return delta != 0U && delta < 0x8000U;
}

// nowMs comes from a monotonic clock. Keeping freshness independent of wall
// time lets the display survive RTC/NTP adjustments without false timeouts.
class Tracker {
public:
    bool accept(const Packet &candidate, std::int64_t nowMs)
    {
        if (fresh(nowMs) && !sequenceForward(candidate.sequence, packet_.sequence)) {
            return false;
        }
        packet_ = candidate;
        lastAcceptedMs_ = nowMs;
        seen_ = true;
        return true;
    }

    bool seen() const { return seen_; }
    bool fresh(std::int64_t nowMs) const
    {
        return seen_ && nowMs >= lastAcceptedMs_ &&
               nowMs - lastAcceptedMs_ <= kFreshMs;
    }
    const Packet &packet() const { return packet_; }

private:
    Packet packet_;
    std::int64_t lastAcceptedMs_ = 0;
    bool seen_ = false;
};

}  // namespace status_v1
