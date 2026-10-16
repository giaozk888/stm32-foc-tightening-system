#ifndef HMI_LOG_DOWNLOAD_H
#define HMI_LOG_DOWNLOAD_H
#include "rpc_can_client.h"
#include <memory>

namespace rpc_can {
enum class DownloadState { Idle, Active, Done, Cancelled, Failed };
// Qt/UI thread owns the CAN socket; upstream TransferThread owns the writer.
class LogDownload {
 public:
    LogDownload();
    ~LogDownload();
    LogDownload(const LogDownload&) = delete;
    LogDownload& operator=(const LogDownload&) = delete;
    bool begin(Client& queryClient, std::uint32_t seed, std::int64_t now);
    void tick(std::int64_t now, const std::function<bool(const std::uint8_t*)>& send);
    void receive(std::uint32_t id, bool extended, bool remote, bool error,
        std::uint8_t length, const std::uint8_t* bytes, std::int64_t now);
    void cancel();
    bool canCancel() const;
    bool active() const;
    DownloadState state() const;
    std::size_t received() const;
    std::size_t total() const;
    const std::uint8_t* data() const;
 private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
}
#endif
