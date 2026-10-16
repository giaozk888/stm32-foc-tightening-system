#pragma once
#include "can_log_v1.h"
#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <algorithm>

namespace can_log {
struct Complete { std::string text; bool sessionStart; };
class Receiver {
public:
    std::optional<Complete> feed(std::uint32_t id, bool extended, bool remote,
                                 bool error, int dlc, const std::uint8_t *data,
                                 std::int64_t now)
    {
        expire(now);
        if (id != CAN_LOG_START_ID && id != CAN_LOG_DATA_ID) return {};
        if (extended || remote || error || dlc != 8 || !data) { ++invalid_; return {}; }
        if (id == CAN_LOG_START_ID) {
            CanLog_Start next{};
            if (!CanLog_DecodeStart(data, &next)) { ++invalid_; return {}; }
            if (haveLast_ && next.record_id == lastId_ && next.crc == lastCrc_) {
                ++duplicates_; return {};
            }
            if (active_) ++incomplete_;
            start_ = next; index_ = 0; active_ = true; startedAt_ = now;
            return {};
        }
        if (!active_) { ++orphan_; return {}; }
        const auto recordId = std::uint16_t(data[0] | (std::uint16_t(data[1]) << 8));
        if (recordId != start_.record_id || data[2] != index_) {
            active_ = false; ++incomplete_; return {};
        }
        const std::size_t offset = std::size_t(index_) * CAN_LOG_CHUNK_SIZE;
        const auto count = std::min<std::size_t>(CAN_LOG_CHUNK_SIZE, start_.length - offset);
        for (std::size_t i = count; i < CAN_LOG_CHUNK_SIZE; ++i)
            if (data[3 + i]) { active_ = false; ++invalid_; return {}; }
        std::copy_n(data + 3, count, text_.data() + offset);
        ++index_;
        if (offset + count < start_.length) return {};
        active_ = false;
        if (CanLog_Crc16(text_.data(), start_.length) != start_.crc) { ++crcErrors_; return {}; }
        lastId_ = start_.record_id; lastCrc_ = start_.crc; haveLast_ = true;
        ++completed_;
        return Complete{std::string(reinterpret_cast<const char *>(text_.data()), start_.length),
                        (start_.flags & CAN_LOG_FLAG_SESSION_START) != 0};
    }
    void expire(std::int64_t now) {
        if (active_ && now - startedAt_ > 10000) { active_ = false; ++incomplete_; }
    }
    void reset() { active_ = false; haveLast_ = false; }
    std::uint64_t incomplete() const { return incomplete_; }
    std::uint64_t crcErrors() const { return crcErrors_; }
    std::uint64_t invalid() const { return invalid_; }
    std::uint64_t completed() const { return completed_; }
private:
    CanLog_Start start_{};
    std::array<std::uint8_t, CAN_LOG_MAX_TEXT> text_{};
    std::int64_t startedAt_ = 0;
    std::uint16_t lastId_ = 0, lastCrc_ = 0;
    std::uint8_t index_ = 0;
    bool active_ = false, haveLast_ = false;
    std::uint64_t incomplete_ = 0, crcErrors_ = 0, invalid_ = 0, orphan_ = 0;
    std::uint64_t completed_ = 0, duplicates_ = 0;
};
} // namespace can_log
