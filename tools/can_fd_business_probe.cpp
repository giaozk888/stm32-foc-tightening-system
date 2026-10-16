// Bounded read-only acceptance. No motion, parameter write, or arbitrary TX.
#include "rpc_can_client.h"
#include "log_download.h"
#include "can_log_receiver.h"
#include "status_v1.h"
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>
#include <array>
#include <chrono>
#include <iostream>
#include <stdexcept>

namespace {
std::int64_t nowMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
struct Fd {
    int value = -1;
    ~Fd() { if (value >= 0) close(value); }
};
void require(bool good, const char* message) {
    if (!good) throw std::runtime_error(message);
}
}

int main(int argc, char** argv) {
    try {
        require(argc == 3 && std::string(argv[1]) == "--permit-read-only-test",
                "Usage: can_fd_business_probe --permit-read-only-test NEW_HISTORY_PATH");
        Fd history;
        history.value = open(argv[2], O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        require(history.value >= 0, "History output must be a fresh writable path");
        Fd socketFd;
        socketFd.value = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_RAW);
        require(socketFd.value >= 0, "SocketCAN open failed");
        int on = 1;
        require(setsockopt(socketFd.value, SOL_CAN_RAW, CAN_RAW_FD_FRAMES, &on, sizeof(on)) == 0,
                "CAN FD socket option rejected");
        ifreq request{};
        std::copy_n("can0", 5, request.ifr_name);
        require(ioctl(socketFd.value, SIOCGIFINDEX, &request) == 0, "can0 missing");
        const int index = request.ifr_ifindex;
        require(ioctl(socketFd.value, SIOCGIFMTU, &request) == 0 && request.ifr_mtu == CANFD_MTU,
                "can0 is not FD MTU 72");
        sockaddr_can address{};
        address.can_family = AF_CAN;
        address.can_ifindex = index;
        require(bind(socketFd.value, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0,
                "CAN socket bind failed");
        std::cout << "BUSINESS READY: CAN FD socket receiving; fixed LOG TEST 4 fixture may now be emitted over UART" << std::endl;
        const auto seed = static_cast<std::uint32_t>(nowMs()) & 0x7fffU;
        rpc_can::Client query(seed + 1);
        rpc_can::LogDownload download;
        status_v1::Tracker tracker;
        can_log::Receiver logs;
        unsigned statuses = 0, fdFrames = 0, txFrames = 0;
        auto send = [&](const std::uint8_t* bytes) {
            canfd_frame frame{};
            frame.can_id = CAN_RPC_REQUEST_ID;
            frame.len = 8;
            frame.flags = 0; // No BRS. No other transmit ID is available.
            std::copy_n(bytes, 8, frame.data);
            const auto result = write(socketFd.value, &frame, CANFD_MTU);
            if (result == CANFD_MTU) ++txFrames;
            return result == CANFD_MTU;
        };
        auto pump = [&]() {
            const auto now = nowMs();
            query.tick(now, send);
            download.tick(now, send);
            pollfd waiting{socketFd.value, POLLIN, 0};
            require(poll(&waiting, 1, 5) >= 0, "Socket poll failed");
            for (unsigned i = 0; i < 256; ++i) {
                canfd_frame frame{};
                const auto length = read(socketFd.value, &frame, CANFD_MTU);
                if (length < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
                require(length == CANFD_MTU, "Classic/error/short frame received in FD-only acceptance");
                require(!(frame.can_id & (CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG)) &&
                        !(frame.flags & (CANFD_BRS | CANFD_ESI)) && frame.len <= 64,
                        "Unexpected FD ID flags, BRS, or error state");
                ++fdFrames;
                const auto timestamp = nowMs();
                query.receive(frame.can_id, false, false, false, frame.len, frame.data, timestamp);
                download.receive(frame.can_id, false, false, false, frame.len, frame.data, timestamp);
                logs.feed(frame.can_id, false, false, false, frame.len, frame.data, timestamp);
                status_v1::Packet packet;
                if (status_v1::decode(frame.can_id, false, false, false, frame.len, frame.data, packet)) {
                    require(packet.mode == 0 && !(packet.flags & 0x09U) && packet.fault == 0,
                            "Telemetry is not idle/fault-free/power-off");
                    if (tracker.accept(packet, timestamp)) ++statuses;
                }
            }
        };
        const std::array<std::pair<std::uint32_t, const char*>, 4> methods{{
            {rpc_readonly::ping, "Ping"}, {rpc_readonly::status, "GetStatus"},
            {rpc_readonly::params, "GetParams"}, {rpc_readonly::diagnostics, "GetDiagnostics"}}};
        for (const auto& method : methods) {
            require(query.begin(method.first, nowMs()), "Query start rejected");
            const auto deadline = nowMs() + 6000;
            while (query.busy() && nowMs() < deadline) pump();
            require(query.state() == rpc_can::State::Success, "Query failed (timeout/protocol/send)");
            if (method.first == rpc_readonly::status) {
                const auto* p = query.result();
                require(rpc_readonly::get32(p + 8) == 0 &&
                        !(rpc_readonly::get32(p + 12) & 1U) &&
                        rpc_readonly::get32(p + 16) == 0 &&
                        rpc_readonly::get32(p + 20) == 1 &&
                        rpc_readonly::get32(p + 24) == 0 &&
                        rpc_readonly::get32(p + 28) == 0,
                        "RPC status does not prove safe latch/control lock");
            }
            if (method.first == rpc_readonly::diagnostics) {
                const auto* p = query.result();
                require(rpc_readonly::get32(p + 4) == 1 && rpc_readonly::get32(p + 24) == 1 &&
                        rpc_readonly::get32(p + 28) == 0 && rpc_readonly::get32(p + 36) == 0,
                        "Diagnostics log/CAN readiness, bus-off, or FIFO overrun failed");
            }
            std::cout << "RPC PASS " << method.second << " bytes=" << query.resultSize() << std::endl;
        }
        require(download.begin(query, seed + 0x10000U, nowMs()), "Official Transfer.Read(3) start rejected");
        const auto deadline = nowMs() + 240000;
        auto nextProgress = nowMs();
        while (download.active() && nowMs() < deadline) {
            pump();
            if (nowMs() >= nextProgress) {
                std::cout << "TRANSFER progress=" << download.received() << "/" << download.total() << std::endl;
                nextProgress = nowMs() + 15000;
            }
        }
        if (download.active()) download.cancel();
        require(download.state() == rpc_can::DownloadState::Done && download.received() > 0,
                "Official Transfer did not complete with peer completion ACK and nonempty history");
        require(tracker.fresh(nowMs()) && statuses >= 5 && logs.completed() >= 4 &&
                logs.crcErrors() == 0 && logs.invalid() == 0,
                "Fresh sequenced telemetry or live log integrity check failed");
        require(write(history.value, download.data(), download.received()) ==
                static_cast<ssize_t>(download.received()) && fsync(history.value) == 0,
                "History save failed");
        std::cout << "BUSINESS PASS FD=1 BRS=0 RPC=4 TRANSFER_READ_RESOURCE=3 bytes="
                  << download.received() << " status_frames=" << statuses
                  << " live_logs=" << logs.completed() << " live_log_incomplete=" << logs.incomplete()
                  << " rx_fd_frames=" << fdFrames << " tx_readonly_frames=" << txFrames
                  << " control_locked=1" << std::endl;
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "BUSINESS FAIL: " << e.what() << std::endl;
        return 1;
    }
}
