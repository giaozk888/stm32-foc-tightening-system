#pragma once
#include "safety_guard.h"
#include "status_v1.h"
#include <cstdint>
#include <array>

namespace safety_report_v1 {
struct Packet {
    std::uint8_t flags = 0;
    std::uint16_t missing = 0;
    std::uint8_t pc4Reasons = 0;
    std::uint8_t pc5Reasons = 0;
    std::uint16_t sequence = 0;
};
inline bool decode(std::uint32_t id, bool extended, bool remote, bool error,
                   std::uint8_t length, const std::uint8_t *data, Packet &out)
{
    if (id != SAFETY_REPORT_ID || extended || remote || error || length != 8U ||
        !data || data[0] != 1U || (data[1] & ~3U) || !(data[1] & 1U) ||
        (data[4] & ~0x1fU) || (data[5] & ~0x1fU) ||
        (!(data[1] & 2U) && (!(data[4] & SAMPLE_ACQUISITION) ||
                            !(data[5] & SAMPLE_ACQUISITION)))) return false;
    const auto mask = static_cast<std::uint16_t>(data[2] | (data[3] << 8));
    if ((mask & ~SAFETY_KNOWN_MASK) || !(mask & SAFETY_BOOT_LOCK) ||
        (data[4] && !(mask & SAFETY_VBUS)) ||
        (data[5] && !(mask & SAFETY_TEMPERATURE))) return false;
    out = {data[1], mask, data[4], data[5],
           static_cast<std::uint16_t>(data[6] | (data[7] << 8))};
    return true;
}
// Diagnostic only: a fresh report never grants motion authority.
class Tracker {
public:
    bool accept(const Packet &candidate, std::int64_t nowMs)
    {
        if (nowMs < 0 || (seen_ && nowMs < lastMs_) ||
            (fresh(nowMs) && !status_v1::sequenceForward(candidate.sequence, packet_.sequence)))
            return false;
        packet_ = candidate;
        lastMs_ = nowMs;
        seen_ = true;
        return true;
    }
    bool fresh(std::int64_t nowMs) const
    { return seen_ && nowMs >= lastMs_ && nowMs - lastMs_ <= SAFETY_FRESH_MS; }
    bool seen() const { return seen_; }
    const Packet &packet() const { return packet_; }
private:
    Packet packet_{};
    std::int64_t lastMs_ = 0;
    bool seen_ = false;
};

struct RawPacket {
    unsigned channel = 0;
    std::array<std::uint16_t, 3> raw{};
    std::uint16_t sequence = 0;
};
inline bool decodeRaw(std::uint32_t id, bool extended, bool remote, bool error,
                      std::uint8_t length, const std::uint8_t *data, RawPacket &out)
{
    if ((id != SAFETY_PC4_RAW_ID && id != SAFETY_PC5_RAW_ID) ||
        extended || remote || error || length != 8U || !data) return false;
    RawPacket candidate;
    candidate.channel = id == SAFETY_PC4_RAW_ID ? 0U : 1U;
    bool unavailable = true;
    for (unsigned i = 0; i < 3; ++i) {
        candidate.raw[i] = static_cast<std::uint16_t>(data[2*i] | (data[2*i+1] << 8));
        if (candidate.raw[i] != UINT16_MAX) unavailable = false;
    }
    if (!unavailable)
        for (auto value : candidate.raw) if (value > 4095U) return false;
    candidate.sequence = static_cast<std::uint16_t>(data[6] | (data[7] << 8));
    out = candidate;
    return true;
}
class RawTracker {
public:
    bool accept(const RawPacket &in, std::int64_t nowMs)
    {
        if (in.channel > 1U || nowMs < 0) return false;
        const auto ch = in.channel;
        if (seen_[ch] && (nowMs < times_[ch] ||
            (nowMs - times_[ch] <= SAFETY_FRESH_MS &&
             !status_v1::sequenceForward(in.sequence, packets_[ch].sequence)))) return false;
        packets_[ch] = in; times_[ch] = nowMs; seen_[ch] = true;
        return true;
    }
    const RawPacket *matching(unsigned channel, const Tracker &report, std::int64_t nowMs) const
    {
        if (channel > 1U || !report.fresh(nowMs) || !seen_[channel] ||
            nowMs < times_[channel] || nowMs - times_[channel] > SAFETY_FRESH_MS ||
            packets_[channel].sequence != report.packet().sequence) return nullptr;
        return &packets_[channel];
    }
private:
    std::array<RawPacket, 2> packets_{};
    std::array<std::int64_t, 2> times_{};
    std::array<bool, 2> seen_{};
};
}
