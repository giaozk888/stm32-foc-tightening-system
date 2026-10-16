#pragma once

#include "pigweed_log.h"
#include <QObject>
#include <QTimer>
#include <QElapsedTimer>
#include <QString>
#include <functional>
#include <utility>

#ifdef Q_OS_LINUX
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>
#endif

// This receiver has no command/write API. Only the explicitly configured
// character device is opened; no automatic serial probing or MCU reset.
class LogSerialReader final : public QObject {
public:
    LogSerialReader(QString path, std::function<void(const std::string &)> onLine,
                    std::function<void()> onSession, QObject *parent = nullptr)
        : QObject(parent), path_(std::move(path)), onLine_(std::move(onLine)),
          onSession_(std::move(onSession))
    {
        clock_.start();
        connect(&timer_, &QTimer::timeout, this, [this] { service(); });
        timer_.start(50);
        state_ = path_.isEmpty() ? QStringLiteral("未配置日志串口")
                               : QStringLiteral("等待日志串口连接");
    }

    ~LogSerialReader() override { closePort(); }
    QString state() const { return state_; }
    QString path() const { return path_; }
    bool connected() const { return fd_ >= 0; }
    std::uint64_t oversized() const { return lines_.oversized(); }
    void reconnect()
    {
        closePort();
        retryAt_ = 0;
        state_ = path_.isEmpty() ? QStringLiteral("未配置日志串口")
                               : QStringLiteral("等待日志串口重新连接");
    }

private:
    void closePort()
    {
#ifdef Q_OS_LINUX
        if (fd_ >= 0) ::close(fd_);
#endif
        fd_ = -1;
        lines_.reset();
    }

    void fail(const QString &reason)
    {
        closePort();
        state_ = reason + QStringLiteral("；2 秒后重连");
        retryAt_ = clock_.elapsed() + 2000;
    }

    void service()
    {
        if (path_.isEmpty()) return;
#ifdef Q_OS_LINUX
        if (fd_ < 0) {
            if (clock_.elapsed() < retryAt_) return;
            if (!path_.startsWith(QStringLiteral("/dev/"))) {
                fail(QStringLiteral("日志端口必须是 /dev 下的串口设备"));
                return;
            }
            const auto device = path_.toLocal8Bit();
            fd_ = ::open(device.constData(), O_RDONLY | O_NONBLOCK | O_NOCTTY | O_CLOEXEC);
            if (fd_ < 0) { fail(QString::fromLocal8Bit(std::strerror(errno))); return; }
            struct stat info {};
            struct termios options {};
            if (::fstat(fd_, &info) != 0 || !S_ISCHR(info.st_mode) ||
                ::flock(fd_, LOCK_EX | LOCK_NB) != 0 || ::tcgetattr(fd_, &options) != 0) {
                fail(QStringLiteral("串口不可用或被其他监听程序占用"));
                return;
            }
            ::cfmakeraw(&options);
            ::cfsetispeed(&options, B115200);
            ::cfsetospeed(&options, B115200);
            options.c_cflag = (options.c_cflag & ~(CSIZE | PARENB | CSTOPB | CRTSCTS | HUPCL)) |
                              CS8 | CLOCAL | CREAD;
            options.c_cc[VMIN] = 0;
            options.c_cc[VTIME] = 0;
            if (::tcsetattr(fd_, TCSANOW, &options) != 0) {
                fail(QString::fromLocal8Bit(std::strerror(errno)));
                return;
            }
            lines_.reset();
            state_ = QStringLiteral("日志串口已连接 · 115200 / 8N1 · 等待记录");
            onSession_();
        }
        struct pollfd event {fd_, POLLIN, 0};
        if (::poll(&event, 1, 0) < 0) {
            if (errno != EINTR) fail(QStringLiteral("串口状态读取失败"));
            return;
        }
        if ((event.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
            fail(QStringLiteral("日志串口已断开"));
            return;
        }
        if ((event.revents & POLLIN) == 0) return;
        // Limit each tick to 16 KiB so log bursts cannot monopolize touch UI.
        for (int batch = 0; batch < 16; ++batch) {
            char bytes[1024];
            const auto count = ::read(fd_, bytes, sizeof(bytes));
            if (count < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) break;
                fail(QString::fromLocal8Bit(std::strerror(errno)));
                return;
            }
            if (count == 0) break;
            for (const auto &line : lines_.feed({bytes, static_cast<std::size_t>(count)}))
                onLine_(line);
        }
#else
        state_ = QStringLiteral("Windows 预览：可导入日志；实时接收在鲁班猫启用");
#endif
    }

    QString path_;
    QString state_;
    int fd_ = -1;
    QTimer timer_;
    QElapsedTimer clock_;
    qint64 retryAt_ = 0;
    pigweed_log::Lines lines_;
    std::function<void(const std::string &)> onLine_;
    std::function<void()> onSession_;
};
