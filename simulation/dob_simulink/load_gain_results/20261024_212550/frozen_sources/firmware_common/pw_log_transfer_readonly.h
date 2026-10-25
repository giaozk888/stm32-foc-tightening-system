#ifndef PW_LOG_TRANSFER_READONLY_H
#define PW_LOG_TRANSFER_READONLY_H
#include "log_transfer_wire.h"
#include "pw_log_backend.h"
#include "pw_transfer/internal/chunk.h"
#include <array>
#include <algorithm>

/* Historical unary implementation, retained for source comparison only.
 * Current CAN builds use official_log_transfer.h + upstream TransferService.
 * ProtocolTask-only, no file writes and no full Transfer Manager dependency.
 * Pins at most 16 sealed records; only a 32-byte serialization slice is copied. */
class PwLogReadSession {
 public:
    using WireChunk = pw::transfer::internal::Chunk;
    using Version = pw::transfer::ProtocolVersion;
    ~PwLogReadSession() { release(); }
    void expire(std::uint32_t now) {
        if (session_ && (std::uint32_t(now-last_) >= 15000U || std::uint32_t(now-started_) >= 600000U)) release();
    }
    pw::Result<pw::ConstByteSpan> process(pw::ConstByteSpan request, pw::ByteSpan output, std::uint32_t now) {
        expire(now);
        log_transfer::Chunk checked;
        if (!log_transfer::decode(reinterpret_cast<const std::uint8_t*>(request.data()), request.size(), checked) ||
            !log_transfer::requestAllowed(checked)) return pw::Status::InvalidArgument();
        const auto parsed = WireChunk::Parse(request);
        if (!parsed.ok()) return parsed.status();
        const auto &input = parsed.value();
        if (input.protocol_version() != Version::kVersionTwo) return pw::Status::InvalidArgument();
        const auto id = input.session_id();
        if (checked.type == log_transfer::Start) {
            if (session_ && session_ != id) return pw::Status::ResourceExhausted();
            if (!session_) {
                if (id == completed_) return pw::Status::FailedPrecondition();
                PW_LogDiagnostics_t diagnostics{};
                PW_Log_GetDiagnostics(&diagnostics);
                if (!diagnostics.ready) return pw::Status::Unavailable();
                session_ = id; started_ = now; total_ = 0;
                count_ = PW_Log_HistorySnapshot(refs_.data(), refs_.size());
                for (std::size_t i = 0; i < count_; ++i) {
                    const auto *record = PwLogStore_View(refs_[i]);
                    if (!record || record->length >= PW_LOG_TEXT_BYTES) { release(); return pw::Status::DataLoss(); }
                    total_ += record->length;
                }
            }
            last_ = now;
            WireChunk reply(Version::kVersionTwo, WireChunk::Type::kStartAck);
            reply.set_session_id(id); reply.set_resource_id(log_transfer::resource); reply.set_remaining_bytes(total_);
            return reply.Encode(output);
        }
        if (checked.type == log_transfer::Completion) {
            if (id != session_ && (id != completed_ || checked.status != completedStatus_)) return pw::Status::NotFound();
            if (id == session_) { completed_ = id; completedStatus_ = checked.status; release(); }
            WireChunk reply(Version::kVersionTwo, WireChunk::Type::kCompletionAck);
            reply.set_session_id(id); reply.set_status(static_cast<pw::Status::Code>(checked.status));
            return reply.Encode(output);
        }
        if (!session_ || id != session_) return pw::Status::NotFound();
        if (input.offset() > total_) return pw::Status::OutOfRange();
        last_ = now;
        std::array<std::byte, log_transfer::block> slice{};
        const auto wanted = std::min<std::uint32_t>(slice.size(), total_ - input.offset());
        std::uint32_t skip = input.offset(), copied = 0;
        for (std::size_t i = 0; i < count_ && copied < wanted; ++i) {
            const auto *record = PwLogStore_View(refs_[i]);
            if (!record) { release(); return pw::Status::DataLoss(); }
            if (skip >= record->length) { skip -= record->length; continue; }
            const auto take = std::min<std::uint32_t>(record->length - skip, wanted - copied);
            std::memcpy(slice.data()+copied, record->text+skip, take); copied += take; skip = 0;
        }
        if (copied != wanted) { release(); return pw::Status::DataLoss(); }
        WireChunk reply(Version::kVersionTwo, WireChunk::Type::kData);
        reply.set_session_id(id); reply.set_offset(input.offset());
        reply.set_payload(pw::ConstByteSpan(slice.data(), copied));
        reply.set_remaining_bytes(total_ - input.offset() - copied);
        return reply.Encode(output);
    }
 private:
    void release() {
        for (std::size_t i = 0; i < count_; ++i) (void)PwLogStore_Release(refs_[i]);
        count_ = 0; session_ = 0; total_ = 0;
    }
    std::array<PwLogRef, log_transfer::historyCapacity> refs_{};
    std::size_t count_ = 0;
    std::uint32_t session_ = 0, total_ = 0, started_ = 0, last_ = 0, completed_ = 0, completedStatus_ = 0;
};
#endif
