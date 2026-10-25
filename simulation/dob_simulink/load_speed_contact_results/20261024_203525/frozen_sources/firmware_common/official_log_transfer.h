#ifndef OFFICIAL_LOG_TRANSFER_H
#define OFFICIAL_LOG_TRANSFER_H
#include "pw_log_backend.h"
#include "pw_log_snapshot.h"
#include "pw_stream/stream.h"
#include "pw_transfer/handler.h"
#include <algorithm>
#include <cstring>
#include <atomic>

namespace official_log_transfer {
constexpr uint32_t resource = 3;
constexpr size_t capacity = 16 * 191;
constexpr size_t block = 32;
constexpr size_t window = 64;
constexpr uint32_t sessionLimitMs = 600000;

// Immutable, seekable view: retransmits read the same pinned records.
class HistoryReader final : public pw::stream::SeekableReader {
 public:
  HistoryReader() = default;
  HistoryReader(const HistoryReader&) = delete;
  HistoryReader& operator=(const HistoryReader&) = delete;
  ~HistoryReader() override { release(); }
  pw::Status prepare() {
    if (active_) return pw::Status::ResourceExhausted();
    PW_LogDiagnostics_t diagnostics{};
    PW_Log_GetDiagnostics(&diagnostics);
    if (!diagnostics.ready) return pw::Status::Unavailable();
    if (!PW_LogSnapshot_Acquire(&snapshot_)) return pw::Status::ResourceExhausted();
    count_ = snapshot_.count;
    total_ = position_ = 0;
    for (size_t i = 0; i < count_; ++i) {
      const auto* record = PwLogStore_View(snapshot_.refs[i]);
      if (!record || record->length >= PW_LOG_TEXT_BYTES) {
        release(); return pw::Status::DataLoss();
      }
      total_ += record->length;
    }
    active_ = true;
    return pw::OkStatus();
  }
  void release() {
    PW_LogSnapshot_Release(&snapshot_);
    count_ = total_ = position_ = 0; active_ = false;
  }
  size_t size() const { return total_; }
 private:
  pw::StatusWithSize DoRead(pw::ByteSpan destination) override {
    if (!active_) return pw::StatusWithSize::FailedPrecondition();
    if (position_ == total_) return pw::StatusWithSize::OutOfRange();
    const size_t wanted = std::min(destination.size(), total_ - position_);
    size_t skip = position_, copied = 0;
    for (size_t i = 0; i < count_ && copied < wanted; ++i) {
      const auto* record = PwLogStore_View(snapshot_.refs[i]);
      if (!record) return pw::StatusWithSize::DataLoss();
      if (skip >= record->length) { skip -= record->length; continue; }
      const size_t take = std::min<size_t>(record->length - skip, wanted - copied);
      std::memcpy(destination.data() + copied, record->text + skip, take);
      copied += take; skip = 0;
    }
    if (copied != wanted) return pw::StatusWithSize::DataLoss();
    position_ += copied;
    return pw::StatusWithSize(copied);
  }
  pw::Status DoSeek(ptrdiff_t offset, Whence origin) override {
    if (!active_) return pw::Status::FailedPrecondition();
    const int64_t base = origin == kBeginning ? 0 : origin == kCurrent ? position_ : total_;
    if (offset < -base || offset > int64_t(total_) - base) return pw::Status::OutOfRange();
    position_ = size_t(base + offset); return pw::OkStatus();
  }
  size_t DoTell() override { return position_; }
  size_t ConservativeLimit(LimitType type) const override {
    return type == LimitType::kRead && active_ ? total_ - position_ : 0;
  }
  PW_LogSnapshot snapshot_{};
  size_t count_ = 0, total_ = 0, position_ = 0;
  bool active_ = false;
};
class HistoryHandler final : public pw::transfer::ReadOnlyHandler {
 public:
  HistoryHandler() : ReadOnlyHandler(resource, reader_) {}
  pw::Status PrepareRead() override {
    const auto status = reader_.prepare();
    if (status.ok()) { started_.store(now_.load()); active_.store(true); }
    return status;
  }
  // A new session cannot reconstruct a previous RAM snapshot after reboot.
  pw::Status PrepareRead(uint32_t) override { return pw::Status::Unimplemented(); }
  void FinalizeRead(pw::Status) override { reader_.release(); active_.store(false); }
  size_t ResourceSize() const override { return reader_.size(); }
  // ProtocolTask supplies milliseconds. Only the transfer thread touches refs.
  void setTime(uint32_t now) { now_.store(now); }
  bool expired() const {
    return active_.load() && uint32_t(now_.load() - started_.load()) >= sessionLimitMs;
  }
 private:
  HistoryReader reader_;
  std::atomic<uint32_t> now_{0}, started_{0};
  std::atomic<bool> active_{false};
};
}
#endif
