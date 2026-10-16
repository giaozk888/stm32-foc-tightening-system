#pragma once

#include <cstdint>
#include <deque>
#include <regex>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pigweed_log {

struct Record {
    std::uint32_t sequence = 0;
    std::uint32_t deviceTickMs = 0;
    std::string level;
    std::string module;
    std::string message;
    bool tokenized = false;
    std::string tokenMetadata;
    std::uint32_t tokenBytes = 0;
    std::string raw;
};

inline bool parse(std::string_view input, Record &out)
{
    if (input.size() > 512U) return false;
    while (!input.empty() && (input.back() == '\r' || input.back() == '\n'))
        input.remove_suffix(1);
    const std::string line(input);
    static const std::regex textPattern(
        R"(^\[PW\]\[([0-9]{1,10})\]\[([0-9]{1,10})ms\]\[(DEBUG|INFO|WARN|ERROR|CRITICAL|FATAL)\]\[([A-Za-z0-9_.-]{1,32})\] ([^\r\n]{0,192})$)");
    static const std::regex tokenPattern(
        R"(^\[PWT\]\[([0-9]{1,10})\]\[([0-9]{1,10})ms\]\[(DEBUG|INFO|WARN|ERROR|CRITICAL|FATAL)\]\[M=([0-9A-Fa-f]{8})\]\[B=([0-9]{1,3})\] (\$[A-Za-z0-9+/=]{1,96})$)");
    std::smatch match;
    const bool tokenized = std::regex_match(line, match, tokenPattern);
    if (!tokenized && !std::regex_match(line, match, textPattern)) return false;
    try {
        const auto sequence = std::stoull(match[1].str());
        const auto tick = std::stoull(match[2].str());
        if (sequence > UINT32_MAX || tick > UINT32_MAX) return false;
        Record candidate;
        candidate.sequence = static_cast<std::uint32_t>(sequence);
        candidate.deviceTickMs = static_cast<std::uint32_t>(tick);
        candidate.level = match[3].str();
        candidate.tokenized = tokenized;
        candidate.raw = line;
        if (tokenized) {
            candidate.module = "TOKEN";
            candidate.tokenMetadata = match[4].str();
            candidate.tokenBytes = static_cast<std::uint32_t>(std::stoul(match[5].str()));
            if (candidate.tokenBytes == 0U || candidate.tokenBytes > 64U) return false;
            candidate.message = match[6].str();
            const auto encoded = candidate.message.substr(1);
            if (encoded.size() != 4U * ((candidate.tokenBytes + 2U) / 3U)) return false;
            const auto padding = (3U - candidate.tokenBytes % 3U) % 3U;
            for (std::size_t i = 0; i < encoded.size(); ++i) {
                const bool shouldPad = i >= encoded.size() - padding;
                if ((encoded[i] == '=') != shouldPad) return false;
            }
        } else {
            candidate.module = match[4].str();
            candidate.message = match[5].str();
        }
        out = std::move(candidate);
        return true;
    } catch (...) {
        return false;
    }
}

class Buffer {
public:
    explicit Buffer(std::size_t capacity = 300U) : capacity_(capacity) {}

    bool append(const Record &record)
    {
        if (capacity_ == 0U) return false;
        if (havePrevious_) {
            const std::uint32_t delta = record.sequence - previousSequence_;
            if (delta == 0U) return false;
            // A lower tick/sequence can be a history dump or a reboot; the
            // transport must explicitly begin a new session. Do not guess.
            if (delta >= 0x80000000U) return false;
            if (delta > 1U) {
                missing_ += delta - 1U;
            }
        }
        previousSequence_ = record.sequence;
        havePrevious_ = true;
        if (records_.size() == capacity_) {
            records_.pop_front();
            ++evicted_;
        }
        records_.push_back(record);
        return true;
    }

    const std::deque<Record> &records() const { return records_; }
    void beginSession() { havePrevious_ = false; ++sessions_; }
    std::uint64_t missing() const { return missing_; }
    std::uint64_t evicted() const { return evicted_; }
    std::uint64_t sessions() const { return sessions_; }

private:
    std::size_t capacity_;
    std::deque<Record> records_;
    std::uint32_t previousSequence_ = 0;
    std::uint64_t missing_ = 0;
    std::uint64_t evicted_ = 0;
    std::uint64_t sessions_ = 0;
    bool havePrevious_ = false;
};

// Handles arbitrary UART chunks. Oversized lines are discarded through LF,
// preventing their suffix from being parsed as a separate log record.
class Lines {
public:
    std::vector<std::string> feed(std::string_view bytes)
    {
        std::vector<std::string> lines;
        for (char byte : bytes) {
            if (byte == '\n') {
                if (!discarding_) lines.push_back(partial_);
                partial_.clear();
                discarding_ = false;
            } else if (!discarding_) {
                if (partial_.size() >= 512U) {
                    partial_.clear();
                    discarding_ = true;
                    ++oversized_;
                } else partial_.push_back(byte);
            }
        }
        return lines;
    }
    void reset() { partial_.clear(); discarding_ = false; }
    std::uint64_t oversized() const { return oversized_; }
private:
    std::string partial_;
    bool discarding_ = false;
    std::uint64_t oversized_ = 0;
};

} // namespace pigweed_log
