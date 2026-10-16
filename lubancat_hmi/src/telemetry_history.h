#pragma once

#include "measurement_v1.h"

#include <cstddef>
#include <cstdint>
#include <deque>

namespace telemetry_history {

constexpr std::int64_t kWindowMs = 30000;
constexpr std::size_t kMaxSamples = 600;

struct Sample {
    std::int64_t timeMs = 0;
    std::int32_t angleMdeg = 0;
    std::int16_t speedDeciRpm = 0;
    std::uint16_t sequence = 0;
};

class History {
public:
    bool accept(const Sample &sample)
    {
        if (!samples_.empty() &&
            (sample.timeMs < samples_.back().timeMs ||
             !measurement_v1::sequenceForward(sample.sequence,
                                               samples_.back().sequence))) {
            return false;
        }
        samples_.push_back(sample);
        while (!samples_.empty() &&
               (sample.timeMs - samples_.front().timeMs > kWindowMs ||
                samples_.size() > kMaxSamples)) {
            samples_.pop_front();
        }
        return true;
    }

    void clear() { samples_.clear(); }
    bool empty() const { return samples_.empty(); }
    const std::deque<Sample> &samples() const { return samples_; }

private:
    std::deque<Sample> samples_;
};

}  // namespace telemetry_history
