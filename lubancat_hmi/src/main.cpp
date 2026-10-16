#include <QApplication>
#include <QDateTime>
#include <QComboBox>
#include <QDir>
#include <QDialog>
#include <QPlainTextEdit>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QFileDialog>
#include <QSaveFile>
#include <QScrollArea>
#include <QFont>
#include <QFontDatabase>
#include <QFrame>
#include <QGridLayout>
#include <QHeaderView>
#include <QHBoxLayout>
#include <QLabel>
#include <QPainter>
#include <QPainterPath>
#include <QPushButton>
#include <QRandomGenerator>
#include <QSocketNotifier>
#include <QStackedWidget>
#include <QStandardPaths>
#include <QStringList>
#include <QTableWidget>
#include <QTimer>
#include <QVBoxLayout>

#include "status_v1.h"
#include "measurement_v1.h"
#include "preflight_observation.h"
#include "telemetry_history.h"
#include "snapshot_store.h"
#include "can_control_v0.h"
#include "control_workflow.h"
#include "log_serial_reader.h"
#include "log_store.h"
#include "can_log_receiver.h"
#include "safety_report_v1.h"
#include "rpc_can_client.h"
#include "rpc_motor_client.h"
#include "log_download.h"
#include "tighten_params.h"
#include "can_wire_profile.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstring>
#include <functional>
#include <memory>
#include <vector>

#ifdef HAS_DRM_UI_PLANE
#include "drm_ui_plane.h"
#endif

#ifdef Q_OS_LINUX
#include <fcntl.h>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <syslog.h>
#include <unistd.h>
#endif

namespace {

constexpr int kWidth = 1024;
constexpr int kHeight = 600;
constexpr int kMaxRows = 80;

struct CanEntry {
    QString time;
    QString id;
    QString data;
    int length = 0;
    bool error = false;
    bool extended = false;
    bool remote = false;
    bool fdFormat = false;
    std::uint32_t rawId = 0;
    std::array<std::uint8_t, 64> rawData{};
};

QString readText(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) return QStringLiteral("—");
    return QString::fromUtf8(file.readAll()).trimmed();
}

QString packetCount(const char *name)
{
    return readText(QStringLiteral("/sys/class/net/can0/statistics/") +
                    QString::fromLatin1(name));
}

bool interfaceUp()
{
#ifdef Q_OS_LINUX
    const int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return false;
    struct ifreq request {};
    std::strncpy(request.ifr_name, "can0", IFNAMSIZ - 1);
    const bool up = ::ioctl(fd, SIOCGIFFLAGS, &request) == 0 &&
                    (request.ifr_flags & IFF_UP) != 0;
    ::close(fd);
    return up;
#else
    return false;
#endif
}

QLabel *label(const QString &text, const char *kind = nullptr)
{
    auto *item = new QLabel(text);
    if (kind) item->setObjectName(QString::fromLatin1(kind));
    item->setWordWrap(true);
    return item;
}

QFrame *panel()
{
    auto *frame = new QFrame;
    frame->setObjectName(QStringLiteral("panel"));
    return frame;
}

QVBoxLayout *column(QWidget *owner, int margin = 16, int spacing = 8)
{
    auto *layout = new QVBoxLayout(owner);
    layout->setContentsMargins(margin, margin, margin, margin);
    layout->setSpacing(spacing);
    return layout;
}

class CanMonitor final : public QObject {
public:
    explicit CanMonitor(std::function<void(const CanEntry &)> onFrame, QObject *parent = nullptr)
        : QObject(parent), onFrame_(std::move(onFrame))
    {
#if defined(HMI_UI_TEST)
        error_ = QStringLiteral("离线界面测试：不打开 CAN");
#elif defined(Q_OS_LINUX)
        fd_ = ::socket(PF_CAN, SOCK_RAW, CAN_RAW);
        if (fd_ < 0) {
            error_ = QString::fromLocal8Bit(std::strerror(errno));
            return;
        }
        if (canFd_) {
            const int enable = 1;
            if (::setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_FD_FRAMES, &enable, sizeof(enable)) < 0) {
                error_ = QString::fromLocal8Bit(std::strerror(errno));
                ::close(fd_);
                fd_ = -1;
                return;
            }
        }
        const int flags = ::fcntl(fd_, F_GETFL, 0);
        if (flags >= 0) ::fcntl(fd_, F_SETFL, flags | O_NONBLOCK);
        struct sockaddr_can address {};
        address.can_family = AF_CAN;
        address.can_ifindex = static_cast<int>(::if_nametoindex("can0"));
        if (address.can_ifindex == 0 ||
            ::bind(fd_, reinterpret_cast<struct sockaddr *>(&address), sizeof(address)) < 0) {
            error_ = QString::fromLocal8Bit(std::strerror(errno));
            ::close(fd_);
            fd_ = -1;
            return;
        }
        notifier_ = new QSocketNotifier(fd_, QSocketNotifier::Read, this);
#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
        connect(notifier_, &QSocketNotifier::activated, this,
                [this](int) { receive(); });
#else
        connect(notifier_, QOverload<int>::of(&QSocketNotifier::activated), this,
                [this](int) { receive(); });
#endif
#else
        error_ = QStringLiteral("SocketCAN 仅在 Linux 鲁班猫上可用");
#endif
    }

    ~CanMonitor() override
    {
#ifdef Q_OS_LINUX
        if (notifier_) notifier_->setEnabled(false);
        if (fd_ >= 0) ::close(fd_);
#endif
    }

    bool ready() const { return fd_ >= 0; }
    QString error() const { return error_; }

    /* No generic control TX API: this method emits only RPC request fragments. */
    bool sendReadOnlyRpcFrame(const std::uint8_t bytes[8])
    {
#if defined(Q_OS_LINUX) && !defined(HMI_UI_TEST)
        if (fd_ < 0 || !bytes || (bytes[0] != CAN_RPC_START && bytes[0] != CAN_RPC_DATA)) return false;
        if (canFd_) {
            struct canfd_frame frame {};
            frame.can_id = CAN_RPC_REQUEST_ID;
            frame.len = 8;
            frame.flags = canBrs_ ? CANFD_BRS : 0;
            std::memcpy(frame.data, bytes, 8);
            return ::write(fd_, &frame, sizeof(frame)) == CANFD_MTU;
        }
        struct can_frame frame {};
        frame.can_id = CAN_RPC_REQUEST_ID; frame.can_dlc = 8;
        std::memcpy(frame.data, bytes, 8);
        return ::write(fd_, &frame, sizeof(frame)) == CAN_MTU;
#else
        (void)bytes; return false;
#endif
    }

private:
    void receive()
    {
#ifdef Q_OS_LINUX
        // A bounded drain keeps a burst of CAN traffic from starving the touch UI.
        for (int i = 0; i < 128; ++i) {
            // canfd_frame shares ID/length/data offsets with can_frame.
            // Read into the larger buffer; never truncate a 64-byte FD frame.
            struct canfd_frame frame {};
            const ssize_t count = ::read(fd_, &frame, sizeof(frame));
            if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
            if (count != CAN_MTU && count != CANFD_MTU) break;
            const bool fdFormat = count == CANFD_MTU;
            const bool errorFrame = (frame.can_id & CAN_ERR_FLAG) != 0;
            if (!errorFrame && !CanWire_ModeMatches(canFd_, fdFormat)) continue;
            if (frame.len > (fdFormat ? CANFD_MAX_DLEN : CAN_MAX_DLEN)) continue;
            CanEntry entry;
            entry.time = QDateTime::currentDateTime().toString(QStringLiteral("HH:mm:ss.zzz"));
            entry.error = (frame.can_id & CAN_ERR_FLAG) != 0;
            entry.fdFormat = fdFormat;
            const bool extended = (frame.can_id & CAN_EFF_FLAG) != 0;
            const canid_t id = frame.can_id & (extended ? CAN_EFF_MASK : CAN_SFF_MASK);
            entry.extended = extended;
            entry.remote = (frame.can_id & CAN_RTR_FLAG) != 0;
            entry.rawId = id;
            entry.id = entry.error ? QStringLiteral("ERR") :
                QStringLiteral("0x%1").arg(id, extended ? 8 : 3, 16, QLatin1Char('0')).toUpper();
            entry.length = frame.len;
            for (int byte = 0; byte < entry.length; ++byte) {
                entry.rawData[byte] = frame.data[byte];
            }
            for (int byte = 0; byte < entry.length; ++byte) {
                if (byte) entry.data += QLatin1Char(' ');
                entry.data += QStringLiteral("%1").arg(frame.data[byte], 2, 16,
                                                        QLatin1Char('0')).toUpper();
            }
            onFrame_(entry);
        }
#endif
    }

    int fd_ = -1;
    bool canFd_ = QCoreApplication::arguments().contains(QStringLiteral("--can-fd"));
    bool canBrs_ = QCoreApplication::arguments().contains(QStringLiteral("--can-fd-brs"));
    QSocketNotifier *notifier_ = nullptr;
    QString error_;
    std::function<void(const CanEntry &)> onFrame_;
};

class LiveTrend final : public QWidget {
public:
    explicit LiveTrend(const telemetry_history::History *history, QWidget *parent = nullptr)
        : QWidget(parent), history_(history)
    {
        setMinimumHeight(155);
    }

    void setState(bool statusFresh, std::int64_t nowMs)
    {
        statusFresh_ = statusFresh;
        nowMs_ = nowMs;
        update();
    }

protected:
    void paintEvent(QPaintEvent *) override
    {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing);
        const QRectF plot = QRectF(rect()).adjusted(48, 23, -14, -26);
        if (plot.width() < 20 || plot.height() < 50) return;
        const qreal gap = 14;
        const qreal laneHeight = (plot.height() - gap) / 2;
        const QRectF angleLane(plot.left(), plot.top(), plot.width(), laneHeight);
        const QRectF speedLane(plot.left(), plot.top() + laneHeight + gap,
                               plot.width(), laneHeight);
        painter.setPen(QPen(QColor("#25354a"), 1));
        for (int i = 0; i <= 5; ++i) {
            const qreal x = plot.left() + plot.width() * i / 5;
            painter.drawLine(QPointF(x, angleLane.top()), QPointF(x, angleLane.bottom()));
            painter.drawLine(QPointF(x, speedLane.top()), QPointF(x, speedLane.bottom()));
        }
        for (const auto &lane : {angleLane, speedLane}) {
            painter.drawLine(lane.topLeft(), lane.topRight());
            painter.drawLine(lane.bottomLeft(), lane.bottomRight());
        }
        painter.setPen(QColor("#50d5ac"));
        painter.drawText(QRectF(1, angleLane.top(), 45, 20), Qt::AlignRight,
                         QStringLiteral("角度°"));
        painter.setPen(QColor("#78a9f5"));
        painter.drawText(QRectF(1, speedLane.top(), 45, 20), Qt::AlignRight,
                         QStringLiteral("rpm"));
        painter.setPen(QColor("#8192a8"));
        painter.drawText(QRectF(plot.left(), plot.bottom() + 2, plot.width(), 20),
                         Qt::AlignCenter, QStringLiteral("最近 30 秒 · 时间向右"));

        if (!statusFresh_ || history_->empty()) {
            painter.setPen(QColor("#8c9db1"));
            painter.drawText(plot, Qt::AlignCenter, statusFresh_
                ? QStringLiteral("等待有效角度 / 转速帧")
                : QStringLiteral("等待 STM32 状态帧"));
            return;
        }
        drawLane(painter, angleLane, true, QColor("#50d5ac"));
        drawLane(painter, speedLane, false, QColor("#78a9f5"));
    }

private:
    void drawLane(QPainter &painter, const QRectF &lane, bool angle, const QColor &color)
    {
        double low = 0;
        double high = 0;
        bool have = false;
        for (const auto &sample : history_->samples()) {
            if (nowMs_ - sample.timeMs > telemetry_history::kWindowMs) continue;
            const double value = angle ? sample.angleMdeg / 1000.0 :
                sample.speedDeciRpm / 10.0;
            if (!have) { low = high = value; have = true; }
            low = std::min(low, value);
            high = std::max(high, value);
        }
        if (!have) return;
        const double pad = std::max((high - low) * 0.1, angle ? 0.05 : 0.2);
        low -= pad;
        high += pad;
        QPainterPath path;
        QPointF last;
        bool started = false;
        for (const auto &sample : history_->samples()) {
            const auto ageMs = nowMs_ - sample.timeMs;
            if (ageMs < 0 || ageMs > telemetry_history::kWindowMs) continue;
            const double value = angle ? sample.angleMdeg / 1000.0 :
                sample.speedDeciRpm / 10.0;
            const QPointF point(lane.right() - lane.width() * ageMs /
                                    telemetry_history::kWindowMs,
                                lane.bottom() - lane.height() * (value - low) / (high - low));
            if (!started) path.moveTo(point);
            else path.lineTo(point);
            started = true;
            last = point;
        }
        painter.save();
        painter.setClipRect(lane);
        painter.setPen(QPen(color, 2));
        painter.drawPath(path);
        if (started) {
            painter.setBrush(color);
            painter.drawEllipse(last, 2.5, 2.5);
        }
        painter.restore();
    }

    const telemetry_history::History *history_;
    std::int64_t nowMs_ = 0;
    bool statusFresh_ = false;
};

class HmiWindow final : public QWidget {
public:
    HmiWindow()
    {
        setObjectName(QStringLiteral("root"));
        setWindowTitle(QStringLiteral("LubanCat 智能拧紧工作站"));
        setFixedSize(kWidth, kHeight);
        setStyleSheet(QStringLiteral(R"QSS(
            QWidget#root { background: #0a111e; color: #ecf3fb; font-family: 'Noto Sans CJK SC', 'Microsoft YaHei'; font-size: 13px; }
            QLabel { color: #dce7f3; }
            QFrame#header, QFrame#sidebar { background: #0d1726; }
            QFrame#panel { background: #131f31; border: 1px solid #24354a; border-radius: 13px; }
            QLabel#title { color: #f3f7fc; font-size: 22px; font-weight: 700; }
            QLabel#section { color: #f0f5fb; font-size: 16px; font-weight: 650; }
            QLabel#value { color: #f7fbff; font-size: 23px; font-weight: 700; }
            QLabel#muted { color: #8c9db1; font-size: 12px; }
            QLabel#accent { color: #42d7ae; font-size: 12px; font-weight: 700; }
            QLabel#warning { color: #ffc46b; font-size: 12px; }
            QLabel#safetyQuality { color: #ffc46b; font-size: 12px; }
            QPushButton#nav { border: 0; border-radius: 9px; text-align: left; padding: 10px 16px; color: #a8bad0; font-size: 15px; }
            QPushButton#nav:hover { background: #1a2b40; color: #f5f8fc; }
            QPushButton#disabledAction { background: #26354a; color: #92a3b8; border: 1px solid #34475f; border-radius: 8px; padding: 9px 16px; }
            QPushButton#snapshotAction { background: #1b3b4b; color: #65e3bb; border: 1px solid #2c7366; border-radius: 8px; font-weight: 700; }
            QPushButton#logChoice { background: #162538; color: #aebfd0; border: 1px solid #34475f; border-radius: 8px; padding: 6px 12px; }
            QPushButton#logChoice:checked { background: #1b3b4b; color: #65e3bb; border: 2px solid #42d7ae; font-weight: 700; }
            QPushButton#rpcReadOnlyAction, QPushButton#rpcLogExport, QPushButton#rpcLogCancel, QPushButton#rpcDetails, QPushButton#motorRpcQuery {
                background: #162538; color: #aebfd0; border: 1px solid #34475f; border-radius: 6px; padding: 4px 8px; }
            QPushButton#rpcReadOnlyAction:disabled, QPushButton#rpcLogExport:disabled, QPushButton#rpcLogCancel:disabled,
            QPushButton#rpcDetails:disabled, QPushButton#motorRpcQuery:disabled { color: #73849a; background: #111c2a; }
            QTableWidget { background: #101b2b; alternate-background-color: #142238; color: #dce9f5; border: 1px solid #2b3f56; border-radius: 8px; gridline-color: #26374a; selection-background-color: #203b50; }
            QHeaderView::section { background: #1b2d42; color: #aebfd0; border: 0; padding: 7px; font-size: 12px; }
        )QSS"));

        auto *root = new QVBoxLayout(this);
        root->setContentsMargins(0, 0, 0, 0);
        root->setSpacing(0);
        root->addWidget(makeHeader());
        auto *body = new QHBoxLayout;
        body->setContentsMargins(0, 0, 0, 0);
        body->setSpacing(0);
        body->addWidget(makeSidebar());
        pages_ = new QStackedWidget;
        pages_->addWidget(makeOverview());
        pages_->addWidget(makeJobs());
        pages_->addWidget(makeControl());
        pages_->addWidget(makeCurves());
        pages_->addWidget(makeRecipes());
        pages_->addWidget(makeDiagnostics());
        pages_->addWidget(makeSnapshots());
        pages_->addWidget(makeLogs());
        body->addWidget(pages_, 1);
        root->addLayout(body, 1);
        activate(0);

        statusClock_.start();
        monitor_ = std::make_unique<CanMonitor>(
            [this](const CanEntry &entry) { onFrame(entry); }, this);
        refreshRpc(); refreshLogDownload(); refreshMotorRpc();
        connect(&rpcTimer_, &QTimer::timeout, this, [this] {
            rpc_.tick(statusClock_.elapsed(), [this](const std::uint8_t *bytes) {
                return monitor_ && monitor_->sendReadOnlyRpcFrame(bytes);
            });
            logDownload_.tick(statusClock_.elapsed(), [this](const std::uint8_t *bytes) {
                return monitor_ && monitor_->sendReadOnlyRpcFrame(bytes);
            });
            motorRpc_.tick(statusClock_.elapsed(), [this](const std::uint8_t *bytes) {
                return monitor_ && monitor_->sendReadOnlyRpcFrame(bytes);
            });
            refreshMotorRpc();
            refreshLogDownload();
            refreshRpc();
        });
        rpcTimer_.start(25);
        startLogReader();
        connect(&statusTimer_, &QTimer::timeout, this, [this] { refreshStatus(); });
        statusTimer_.start(200);
        refreshStatus();
        connect(&logTimer_, &QTimer::timeout, this, [this] { refreshLogs(); });
        logTimer_.start(250);
        refreshLogs();
    }

    void startLogReader()
    {
        logReader_.reset();
        logReader_ = std::make_unique<LogSerialReader>(
            logTransportIndex_ == 1 ?
            qEnvironmentVariable("LUBANCAT_HMI_LOG_PORT") : QString(),
            [this](const std::string &line) {
                if (logTransportIndex_ != 1) return;
                if (logs_.acceptLive(line, logReader_->path())) {
                    logs_.setLastLiveMs(statusClock_.elapsed());
                    logsDirty_ = true;
                    const auto &record = logs_.entries().last().record;
                    // Receipt metadata only; imported history does not produce
                    // this marker. Keep message contents out of system journal.
#ifdef Q_OS_LINUX
                    // openvt redirects stderr to the VT; use syslog so receipt
                    // metadata is inspectable without opening the UART twice.
                    ::syslog(LOG_INFO, "PW_LOG_RX source=UART sequence=%u tick_ms=%u level=%s tokenized=%d",
#else
                    qInfo("PW_LOG_RX source=UART sequence=%u tick_ms=%u level=%s tokenized=%d",
#endif
                          static_cast<unsigned>(record.sequence),
                          static_cast<unsigned>(record.deviceTickMs),
                          record.level.c_str(), record.tokenized ? 1 : 0);
                }
            }, [this] { logs_.beginLiveSession(); }, this);
    }

    void activate(int page)
    {
        pages_->setCurrentIndex(page);
        for (size_t i = 0; i < nav_.size(); ++i) {
            nav_[i]->setStyleSheet(i == static_cast<size_t>(page)
                ? QStringLiteral("background:#1b3b4b;color:#65e3bb;font-weight:700;")
                : QString());
        }
        if (page == 6) refreshSnapshots();
        if (page == 7) refreshLogs();
    }

#ifdef HMI_UI_TEST
    void injectTestFrame(const CanEntry &entry) { onFrame(entry); }
    void refreshTestStatus() { refreshStatus(); }
#endif

    bool importLogFile(const QString &path)
    {
        QString result;
        const bool ok = logs_.importText(path, result);
        logResult_->setText(result);
        logsDirty_ = true;
        refreshLogs();
        return ok;
    }

    bool exportLogFile(const QString &directory)
    {
        QString result;
        const bool ok = logs_.exportJsonl(directory, result);
        logResult_->setText(ok ? QStringLiteral("已保存：%1").arg(QFileInfo(result).fileName())
                              : result);
        if (ok) qInfo("Pigweed log exported: %s", qPrintable(result));
        return ok;
    }

    void selectLogSource(bool uart)
    {
        const int index = uart ? 1 : 0;
        for (int i = 0; i < 2; ++i) logTransportButtons_[i]->setChecked(i == index);
        if (logTransportIndex_ == index) return;
        logTransportIndex_ = index;
        canLogs_.reset(); logs_.beginLiveSession(); logs_.setLastLiveMs(-1);
        startLogReader(); refreshLogs();
    }

    void selectLogFilter(int index)
    {
        if (index < 0 || index >= 4) return;
        logFilterIndex_ = index;
        for (int i = 0; i < 4; ++i) logFilterButtons_[i]->setChecked(i == index);
        logsDirty_ = true;
        refreshLogs();
    }

private:
    QFrame *makeHeader()
    {
        auto *header = new QFrame;
        header->setObjectName(QStringLiteral("header"));
        header->setFixedHeight(65);
        auto *row = new QHBoxLayout(header);
        row->setContentsMargins(22, 7, 22, 7);
        auto *brand = label(QStringLiteral("●"), "accent");
        brand->setStyleSheet(QStringLiteral("color:#44d7ac;font-size:29px;"));
        row->addWidget(brand);
        auto *name = label(QStringLiteral("LUBANCAT  /  智能拧紧工作站"), "title");
        name->setWordWrap(false);
        row->addWidget(name);
        row->addStretch();
        clock_ = label(QString(), "muted");
        clock_->setWordWrap(false);
        row->addWidget(clock_);
        linkPill_ = label(QStringLiteral("CAN 检查中"));
        linkPill_->setAlignment(Qt::AlignCenter);
        linkPill_->setFixedSize(118, 34);
        row->addSpacing(18);
        row->addWidget(linkPill_);
        return header;
    }

    QFrame *makeSidebar()
    {
        auto *sidebar = new QFrame;
        sidebar->setObjectName(QStringLiteral("sidebar"));
        sidebar->setFixedWidth(168);
        auto *layout = column(sidebar, 14, 9);
        layout->addSpacing(8);
        layout->addWidget(label(QStringLiteral("操作中心"), "muted"));
        const QStringList names = {QStringLiteral("总览"), QStringLiteral("作业"),
                                   QStringLiteral("控制"), QStringLiteral("曲线"), QStringLiteral("配方"),
                                   QStringLiteral("诊断"), QStringLiteral("记录"), QStringLiteral("日志")};
        for (int i = 0; i < names.size(); ++i) {
            auto *button = new QPushButton(QStringLiteral("  %1").arg(names[i]));
            button->setObjectName(QStringLiteral("nav"));
            button->setFixedHeight(40);
            button->setCursor(Qt::PointingHandCursor);
            connect(button, &QPushButton::clicked, this, [this, i] { activate(i); });
            nav_.push_back(button);
            layout->addWidget(button);
        }
        layout->addStretch();
        layout->addWidget(label(QStringLiteral("MONITOR MODE"), "accent"));
        layout->addWidget(label(QStringLiteral("遥测 / 只读查询\n控制功能未开放"), "muted"));
        layout->addSpacing(11);
        return sidebar;
    }

    QWidget *pageBase(const QString &title, const QString &subtitle, QVBoxLayout **content)
    {
        auto *page = new QWidget;
        page->setStyleSheet(QStringLiteral("background:#0a111e;"));
        auto *layout = column(page, 18, 11);
        auto *heading = new QHBoxLayout;
        auto *names = new QVBoxLayout;
        names->setSpacing(1);
        auto *titleLabel = label(title, "title");
        titleLabel->setWordWrap(false);
        auto *subtitleLabel = label(subtitle, "muted");
        subtitleLabel->setWordWrap(false);
        names->addWidget(titleLabel);
        names->addWidget(subtitleLabel);
        heading->addLayout(names);
        heading->addStretch();
        layout->addLayout(heading);
        *content = layout;
        return page;
    }

    QFrame *metric(const QString &name, const QString &value, const QString &note,
                   QLabel **valueLabel = nullptr)
    {
        auto *card = panel();
        auto *layout = column(card, 13, 4);
        layout->addWidget(label(name, "muted"));
        auto *v = label(value, "value");
        layout->addWidget(v);
        layout->addWidget(label(note, "muted"));
        if (valueLabel) *valueLabel = v;
        return card;
    }

    QWidget *makeOverview()
    {
        QVBoxLayout *layout = nullptr;
        QWidget *page = pageBase(QStringLiteral("设备总览"),
            QStringLiteral("工业拧紧系统 · 实时链路与设备概况"), &layout);
        auto *cards = new QHBoxLayout;
        cards->setSpacing(10);
        cards->addWidget(metric(QStringLiteral("STM32 状态"), QStringLiteral("等待状态帧"),
                                QStringLiteral("只读 0x180 · 控制未开放"), &workValue_), 1);
        cards->addWidget(metric(QStringLiteral("相对机械角"), QStringLiteral("— °"),
                                QStringLiteral("0x181 · 未标定扭矩"), &angleValue_), 1);
        cards->addWidget(metric(QStringLiteral("q 轴电流"), QStringLiteral("— A"),
                                QStringLiteral("0x181 · 非扭矩"), &currentValue_), 1);
        cards->addWidget(metric(QStringLiteral("机械转速"), QStringLiteral("— rpm"),
                                QStringLiteral("0x182 · 0.1 rpm"), &speedValue_), 1);
        cards->addWidget(metric(QStringLiteral("母线估算"), QStringLiteral("— V"),
                                QStringLiteral("0x182 · 空闲时有效"), &vbusValue_), 1);
        layout->addLayout(cards);

        auto *middle = new QHBoxLayout;
        middle->setSpacing(10);
        auto *curveCard = panel();
        auto *curveLayout = column(curveCard, 14, 3);
        curveLayout->addWidget(label(QStringLiteral("实时角度 / 转速 · 非扭矩"), "section"));
        overviewTrend_ = new LiveTrend(&trendHistory_);
        curveLayout->addWidget(overviewTrend_, 1);
        middle->addWidget(curveCard, 7);
        auto *linkCard = panel();
        auto *linkLayout = column(linkCard, 14, 9);
        linkLayout->addWidget(label(QStringLiteral("通信概况"), "section"));
        linkLayout->addWidget(label(QStringLiteral("接口接收 / 发出"), "muted"));
        counts_ = label(QStringLiteral("— / —"), "value");
        linkLayout->addWidget(counts_);
        linkLayout->addWidget(label(QStringLiteral("最近收到的 CAN 帧"), "muted"));
        latest_ = label(QStringLiteral("尚无新帧"));
        latest_->setStyleSheet(QStringLiteral("color:#51d7af;font-size:13px;"));
        linkLayout->addWidget(latest_);
        linkLayout->addStretch();
        middle->addWidget(linkCard, 4);
        layout->addLayout(middle, 1);

        auto *notice = panel();
        auto *noticeLayout = column(notice, 12, 3);
        noticeLayout->addWidget(label(QStringLiteral("安全边界  /  READ ONLY"), "accent"));
        noticeLayout->addWidget(label(QStringLiteral(
            "只读遥测与日志，支持手动 RPC 查询；电流不能直接当作扭矩。"
            "扭矩标定和安全联锁尚未验收。"
            "启动、停止、配方下发和升级入口均未启用。"), "muted"));
        layout->addWidget(notice);
        return page;
    }

    QWidget *makeJobs()
    {
        QVBoxLayout *layout = nullptr;
        QWidget *page = pageBase(QStringLiteral("启动前检查"),
            QStringLiteral("只读观测 · 不是安全验收 · 不发送控制帧"), &layout);
        auto *summary = panel();
        auto *summaryLayout = column(summary, 15, 4);
        summaryLayout->addWidget(label(QStringLiteral("不可启动 · 控制入口未开放"), "section"));
        summaryLayout->addWidget(label(QStringLiteral(
            "下列项目仅来自 0x180–0x182 遥测；绿色只代表相应字段已观测，"
            "不代表硬件安全、可运行或拧紧合格。"), "muted"));
        layout->addWidget(summary);

        auto *observed = panel();
        auto *observedLayout = column(observed, 15, 8);
        observedLayout->addWidget(label(QStringLiteral("实时遥测观察"), "section"));
        auto *checks = new QGridLayout;
        checks->setHorizontalSpacing(15);
        checks->setVerticalSpacing(8);
        const auto addCheck = [checks](int row, int column, const QString &name,
                                       QLabel **value) {
            auto *cell = new QVBoxLayout;
            cell->setSpacing(1);
            cell->addWidget(label(name, "muted"));
            *value = label(QStringLiteral("未知"));
            cell->addWidget(*value);
            checks->addLayout(cell, row, column);
        };
        addCheck(0, 0, QStringLiteral("STM32 状态帧"), &preflightStatus_);
        addCheck(0, 1, QStringLiteral("工作模式"), &preflightMode_);
        addCheck(1, 0, QStringLiteral("软件故障标志/码"), &preflightFault_);
        addCheck(1, 1, QStringLiteral("编码器有效标志"), &preflightEncoder_);
        addCheck(2, 0, QStringLiteral("角度 · 同序号"), &preflightAngle_);
        addCheck(2, 1, QStringLiteral("转速 · 同序号"), &preflightSpeed_);
        addCheck(3, 0, QStringLiteral("母线估算 · 同序号"), &preflightVbus_);
        addCheck(3, 1, QStringLiteral("驱动 SD 输出 · 非回读"), &preflightSd_);
        observedLayout->addLayout(checks);
        layout->addWidget(observed);

        auto *missing = panel();
        auto *missingLayout = column(missing, 15, 4);
        missingLayout->addWidget(label(QStringLiteral("仍缺可信验证 / 控制持续禁用"), "warning"));
        missingLayout->addWidget(label(QStringLiteral(
            "物理急停、功率级状态、ANALOG SAFE 锁存均未由当前 CAN 帧回读；"
            "配方范围、扭矩标定、通信可靠性和固件控制验收也未完成。"), "muted"));
        layout->addWidget(missing);
        layout->addStretch();
        return page;
    }

    QWidget *makeCurves()
    {
        QVBoxLayout *layout = nullptr;
        QWidget *page = pageBase(QStringLiteral("实时趋势"),
            QStringLiteral("只读角度与转速 · 最近 30 秒"), &layout);
        auto *curve = panel();
        auto *curveLayout = column(curve, 17, 10);
        curveLayout->addWidget(label(QStringLiteral("角度 / 转速趋势"), "section"));
        detailTrend_ = new LiveTrend(&trendHistory_);
        detailTrend_->setMinimumHeight(260);
        curveLayout->addWidget(detailTrend_, 1);
        layout->addWidget(curve, 1);
        auto *actions = panel();
        auto *actionsRow = new QHBoxLayout(actions);
        actionsRow->setContentsMargins(17, 10, 17, 10);
        auto *save = new QPushButton(QStringLiteral("保存当前只读快照"));
        save->setFixedSize(190, 40);
        save->setStyleSheet(QStringLiteral(
            "background:#1b3b4b;color:#65e3bb;border:1px solid #2c7366;"
            "border-radius:8px;font-weight:700;"));
        connect(save, &QPushButton::clicked, this, [this] { saveCurrentSnapshot(); });
        actionsRow->addWidget(save);
        snapshotResult_ = label(QStringLiteral("仅诊断记录，非拧紧作业；需至少 2 个新鲜样本"), "muted");
        actionsRow->addWidget(snapshotResult_, 1);
        layout->addWidget(actions);
        return page;
    }

    QWidget *makeControl()
    {
        QVBoxLayout *layout = nullptr;
        QWidget *page = pageBase(QStringLiteral("控制链路 · 未开放"),
            QStringLiteral("协议预演与回执观察；本界面不发控制帧"), &layout);
        // The safety explanation and replies may grow after a query. Keep
        // their full height on the 1024x600 panel instead of clipping labels.
        auto *scroll = new QScrollArea;
        scroll->setObjectName(QStringLiteral("motorControlScroll"));
        scroll->setWidgetResizable(true);
        scroll->setFrameShape(QFrame::NoFrame);
        scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        auto *content = new QWidget;
        auto *controls = column(content, 0, 11);
        controls->setSizeConstraint(QLayout::SetMinAndMaxSize);
        scroll->setWidget(content);
        layout->addWidget(scroll, 1);
        auto *guard = panel();
        guard->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Minimum);
        auto *guardLayout = column(guard, 17, 6);
        guardLayout->addWidget(label(QStringLiteral("电机控制锁定 / MOTOR CONTROL LOCKED"),
                                     "warning"));
        guardLayout->addWidget(label(QStringLiteral(
            "当前没有物理急停与功率级可信回读的验收，CAN 可靠性及配方也未完成。"
            "下方 STOP 不是急停；本页不会解除 ANALOG SAFE，也不会启动或停止电机。"),
            "muted"));
        controlGate_ = label(QStringLiteral("正在核对控制联锁…"), "warning");
        controlGate_->setObjectName(QStringLiteral("motorControlGate"));
        guardLayout->addWidget(controlGate_);
        motorRpcQuery_ = new QPushButton(QStringLiteral("查询电机 RPC 服务（不执行动作）"));
        motorRpcQuery_->setObjectName(QStringLiteral("motorRpcQuery"));
        motorRpcQuery_->setFixedHeight(36);
        connect(motorRpcQuery_, &QPushButton::clicked, this, [this] {
            if (!rpcCanAvailable() || rpc_.busy() || logDownload_.active() || motorRpc_.busy()) return;
            if (motorRpc_.begin(motor_rpc::status, statusClock_.elapsed())) refreshMotorRpc();
        });
        guardLayout->addWidget(motorRpcQuery_);
        motorRpcResult_ = label(QStringLiteral("需新电机服务固件；仅查询，ARM/START/STOP 保持锁定。"), "muted");
        motorRpcResult_->setObjectName(QStringLiteral("motorRpcResult"));
        motorRpcResult_->setWordWrap(true);
        guardLayout->addWidget(motorRpcResult_);
        controls->addWidget(guard);

        auto *actions = panel();
        actions->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Minimum);
        auto *actionsLayout = column(actions, 17, 10);
        actionsLayout->addWidget(label(QStringLiteral("作业命令"), "section"));
        auto *row = new QHBoxLayout;
        for (const QString &name : {QStringLiteral("ARM · 锁定"),
                                    QStringLiteral("START · 锁定"),
                                    QStringLiteral("STOP · 锁定")}) {
            auto *button = new QPushButton(name);
            button->setObjectName(QStringLiteral("disabledAction"));
            button->setEnabled(false);
            button->setFixedHeight(43);
            row->addWidget(button);
        }
        actionsLayout->addLayout(row);
        actionsLayout->addWidget(label(QStringLiteral(
            "使能条件必须由 STM32 本机独立验证；收到协议回执不等于执行或安全停机。"),
            "muted"));
        controls->addWidget(actions);

        auto *protocol = panel();
        protocol->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Minimum);
        auto *protocolLayout = column(protocol, 17, 9);
        protocolLayout->addWidget(label(QStringLiteral("离线协议预演 · 绝不发送"), "section"));
        auto *previews = new QHBoxLayout;
        const auto addPreview = [this, previews](const QString &name, uint8_t opcode) {
            auto *button = new QPushButton(name);
            button->setFixedHeight(40);
            button->setCursor(Qt::PointingHandCursor);
            button->setStyleSheet(QStringLiteral(
                "background:#1b3b4b;color:#65e3bb;border:1px solid #2c7366;"
                "border-radius:8px;font-weight:700;"));
            connect(button, &QPushButton::clicked, this,
                    [this, opcode] { previewControl(opcode); });
            previews->addWidget(button);
        };
        addPreview(QStringLiteral("预演 ARM"), CAN_CONTROL_V0_ARM);
        addPreview(QStringLiteral("预演 START"), CAN_CONTROL_V0_START);
        addPreview(QStringLiteral("预演 STOP"), CAN_CONTROL_V0_STOP);
        protocolLayout->addLayout(previews);
        controlPreview_ = label(QStringLiteral("点选预演，仅展示 0x200 数据布局，不写 can0。"),
                                "muted");
        protocolLayout->addWidget(controlPreview_);
        controlReply_ = label(QStringLiteral("0x280 回执：尚无（外部帧不代表本机发起命令）"),
                              "muted");
        protocolLayout->addWidget(controlReply_);
        controls->addWidget(protocol);
        controls->addStretch();
        return page;
    }

    void previewControl(uint8_t opcode)
    {
        const CanControlV0_Request request = {opcode, 1U, 0U,
            static_cast<uint16_t>(opcode == CAN_CONTROL_V0_STOP ? 0U : 1U)};
        uint8_t data[8] = {0};
        if (CanControlV0_EncodeRequest(&request, data) == 0U) {
            controlPreview_->setText(QStringLiteral("协议预演编码失败；未发送"));
            return;
        }
        QString hex;
        for (uint8_t byte : data) {
            if (!hex.isEmpty()) hex += QLatin1Char(' ');
            hex += QStringLiteral("%1").arg(byte, 2, 16, QLatin1Char('0')).toUpper();
        }
        controlPreview_->setText(QStringLiteral("仅本地预演：0x200#%1 · 未发送 · 不能控制电机")
                                     .arg(hex));
    }

    QWidget *makeLogs()
    {
        QVBoxLayout *layout = nullptr;
        auto *page = pageBase(QStringLiteral("设备日志 · Pigweed"),
            QStringLiteral("CAN 主链路 / USB-TTL 备用 / 级别筛选与导出"), &layout);
        auto *connection = panel();
        auto *connectionLayout = column(connection, 12, 5);
        logConnection_ = label(QStringLiteral("等待日志接收端"), "accent");
        logStats_ = label(QStringLiteral("缓存 0 / 300"), "muted");
        connectionLayout->addWidget(logConnection_);
        auto *transportRow = new QHBoxLayout;
        const QString transportLabels[] = {QStringLiteral("CAN 主链路"), QStringLiteral("USB-TTL 备用")};
        for (int i = 0; i < 2; ++i) {
            auto *button = new QPushButton(transportLabels[i]);
            button->setObjectName(QStringLiteral("logChoice"));
            button->setProperty("logSourceIndex", i);
            button->setCheckable(true);
            button->setChecked(i == 0);
            button->setMinimumHeight(44);
            logTransportButtons_[i] = button;
            transportRow->addWidget(button);
            connect(button, &QPushButton::clicked, this, [this, i] { selectLogSource(i == 1); });
        }
        connectionLayout->addLayout(transportRow);
        connectionLayout->addWidget(logStats_);
        layout->addWidget(connection);
        auto *filters = new QHBoxLayout;
        const QString filterLabels[] = {QStringLiteral("全部级别"), QStringLiteral("INFO 及以上"),
            QStringLiteral("WARN 及以上"), QStringLiteral("ERROR 及以上")};
        for (int i = 0; i < 4; ++i) {
            auto *button = new QPushButton(filterLabels[i]);
            button->setObjectName(QStringLiteral("logChoice"));
            button->setProperty("logFilterIndex", i);
            button->setCheckable(true);
            button->setChecked(i == 0);
            button->setMinimumHeight(44);
            logFilterButtons_[i] = button;
            filters->addWidget(button);
            connect(button, &QPushButton::clicked, this, [this, i] { selectLogFilter(i); });
        }
        layout->addLayout(filters);
        auto *actions = new QHBoxLayout;
        auto *pause = new QPushButton(QStringLiteral("暂停滚动"));
        pause->setCheckable(true);
        connect(pause, &QPushButton::toggled, this, [this, pause](bool checked) {
            logPaused_ = checked;
            pause->setText(checked ? QStringLiteral("恢复滚动") : QStringLiteral("暂停滚动"));
            logsDirty_ = true;
            refreshLogs();
        });
        auto *import = new QPushButton(QStringLiteral("导入日志"));
        connect(import, &QPushButton::clicked, this, [this] {
            const auto path = QFileDialog::getOpenFileName(this, QStringLiteral("选择 UART 日志文件"),
                QString(), QStringLiteral("日志文件 (*.log *.txt);;所有文件 (*)"));
            if (!path.isEmpty()) importLogFile(path);
        });
        auto *save = new QPushButton(QStringLiteral("保存日志"));
        connect(save, &QPushButton::clicked, this, [this] {
            exportLogFile(qEnvironmentVariable("LUBANCAT_HMI_LOG_EXPORT_DIR",
                QStandardPaths::writableLocation(QStandardPaths::AppDataLocation) +
                QStringLiteral("/logs")));
        });
        auto *reconnect = new QPushButton(QStringLiteral("重新连接"));
        connect(reconnect, &QPushButton::clicked, this, [this] {
            if (logReader_) logReader_->reconnect();
            canLogs_.reset(); logs_.beginLiveSession();
            logs_.setLastLiveMs(-1);
            logResult_->setText(QStringLiteral("已重置日志接收会话；不会重启 CAN 或复位 STM32。"));
            refreshLogs();
        });
        for (auto *button : {pause, import, save, reconnect}) {
            button->setObjectName(QStringLiteral("snapshotAction"));
            button->setMinimumHeight(44);
            actions->addWidget(button);
        }
        layout->addLayout(actions);
        logTable_ = new QTableWidget(0, 5);
        logTable_->setObjectName(QStringLiteral("pigweedLogTable"));
        logTable_->setHorizontalHeaderLabels({QStringLiteral("序号 / 来源"), QStringLiteral("设备时间"),
            QStringLiteral("级别"), QStringLiteral("模块"), QStringLiteral("消息")});
        logTable_->verticalHeader()->hide();
        logTable_->setEditTriggers(QAbstractItemView::NoEditTriggers);
        logTable_->setSelectionBehavior(QAbstractItemView::SelectRows);
        logTable_->setAlternatingRowColors(true);
        logTable_->setWordWrap(false);
        logTable_->setColumnWidth(0, 130);
        logTable_->setColumnWidth(1, 100);
        logTable_->setColumnWidth(2, 82);
        logTable_->setColumnWidth(3, 95);
        logTable_->horizontalHeader()->setStretchLastSection(true);
        layout->addWidget(logTable_, 1);
        logResult_ = label(QStringLiteral("压缩日志以 token 显示；解码需与当前固件匹配的 ELF 字典。"), "muted");
        layout->addWidget(logResult_);
        return page;
    }

    void refreshLogs()
    {
        if (!logReader_) return;
        const auto age = logs_.lastLiveMs() < 0 ? -1 : statusClock_.elapsed() - logs_.lastLiveMs();
        const auto activity = age < 0 ? QStringLiteral("尚无实时记录") :
            QStringLiteral("最近日志 %1 秒前").arg(age / 1000);
        canLogs_.expire(statusClock_.elapsed());
        const bool canMode = logTransportIndex_ == 0;
        const auto canState = canLogStatsAt_ < 0 ? QStringLiteral("CAN 主链路 · 等待日志协议") :
            statusClock_.elapsed() - canLogStatsAt_ <= 3000 ? QStringLiteral("CAN 日志状态新鲜") :
            QStringLiteral("CAN 日志状态已过期");
        logConnection_->setText((canMode ? canState : logReader_->state()) + QStringLiteral(" · ") + activity);
        logStats_->setText(QStringLiteral("缓存 %1 / 300  · 缺序号 %2  · 覆盖 %3  · 跳过 %4  · 超长行 %5%6")
            .arg(logs_.entries().size()).arg(logs_.missing()).arg(logs_.evicted())
            .arg(logs_.ignored()).arg(logReader_->oversized())
            .arg(logPaused_ ? QStringLiteral("  · 显示暂停，接收继续") : QString()));
        if (canMode) logStats_->setText(logStats_->text() +
            QStringLiteral("\nCAN 完整 %1 / 未完整 %2 / CRC 错误 %3 · 设备丢弃 %4 / 过期 %5")
            .arg(canLogs_.completed()).arg(canLogs_.incomplete()).arg(canLogs_.crcErrors())
            .arg(canLogStatsAt_ < 0 ? QStringLiteral("--") : QString::number(canQueueDrop_))
            .arg(canLogStatsAt_ < 0 ? QStringLiteral("--") : QString::number(canStaleDrop_)));
        if (!logsDirty_ || logPaused_) return;
        logTable_->setUpdatesEnabled(false);
        logTable_->setRowCount(0);
        const int thresholds[] = {0, 2, 3, 4};
        for (const auto &entry : logs_.entries()) {
            const auto &record = entry.record;
            const int severity = record.level == "DEBUG" ? 1 : record.level == "INFO" ? 2 :
                record.level == "WARN" ? 3 : record.level == "ERROR" ? 4 :
                record.level == "CRITICAL" ? 5 : 7;
            if (severity < thresholds[logFilterIndex_]) continue;
            const int row = logTable_->rowCount();
            logTable_->insertRow(row);
            const QString values[] = {
                QStringLiteral("%1 · %2").arg(record.sequence)
                    .arg(entry.imported ? QStringLiteral("历史") :
                        entry.source == QStringLiteral("CAN can0") ? QStringLiteral("CAN") : QStringLiteral("UART")),
                QStringLiteral("%1 ms").arg(record.deviceTickMs),
                QString::fromStdString(record.level), QString::fromStdString(record.module),
                QString::fromStdString(record.message) +
                    (record.tokenized ? QStringLiteral("  [待字典解码]") : QString())};
            for (int col = 0; col < 5; ++col) {
                auto *item = new QTableWidgetItem(values[col]);
                item->setToolTip(QStringLiteral("来源：%1\n会话：%2\n%3")
                    .arg(entry.source).arg(entry.session).arg(QString::fromStdString(record.raw)));
                if (severity >= 4) item->setForeground(QColor("#ff8d87"));
                else if (severity == 3) item->setForeground(QColor("#ffc46b"));
                logTable_->setItem(row, col, item);
            }
        }
        logTable_->scrollToBottom();
        logTable_->setUpdatesEnabled(true);
        logsDirty_ = false;
    }

    void saveCurrentSnapshot()
    {
        const auto nowMs = statusClock_.elapsed();
        if (!statusTracker_.fresh(nowMs) || !motorTracker_.fresh(nowMs) ||
            !electricalTracker_.fresh(nowMs) || trendHistory_.samples().size() < 2 ||
            nowMs - trendHistory_.samples().back().timeMs > measurement_v1::kFreshMs) {
            snapshotResult_->setText(QStringLiteral("未保存：当前测量不新鲜或样本不足"));
            return;
        }
        const auto result = snapshot_store::save(snapshotDatabasePath(), trendHistory_.samples(),
                                                  QDateTime::currentDateTimeUtc());
        snapshotResult_->setText(result.ok
            ? QStringLiteral("诊断快照 #%1：%2 点，缺序号 %3；时钟未校验")
                  .arg(result.captureId).arg(result.sampleCount).arg(result.missingSequences)
            : QStringLiteral("未保存：%1").arg(result.error));
    }

    QString snapshotDatabasePath() const
    {
        const QString base = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
        return qEnvironmentVariable("LUBANCAT_HMI_RECORD_DB",
                                    base + QStringLiteral("/telemetry.sqlite3"));
    }

    QString snapshotExportDirectory() const
    {
        const QString base = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
        return qEnvironmentVariable("LUBANCAT_HMI_EXPORT_DIR",
                                    base + QStringLiteral("/exports"));
    }

    QWidget *makeRecipes()
    {
        QVBoxLayout *layout = nullptr;
        QWidget *page = pageBase(QStringLiteral("拧紧配方"),
            QStringLiteral("策略配置、版本管理与安全下发"), &layout);
        auto *card = panel();
        auto *cardLayout = column(card, 19, 12);
        cardLayout->addWidget(label(QStringLiteral("暂无已验证配方"), "section"));
        cardLayout->addWidget(label(QStringLiteral(
            "计划字段：目标扭矩、扭矩上/下限、目标角度、转速、停止条件、超时和配方版本。"), "muted"));
        cardLayout->addWidget(label(QStringLiteral(
            "只有在传感器标定、STM32 参数校验、作业状态机和急停联锁全部验收后，"
            "才允许开启编辑与下发。"), "warning"));
        auto *send = new QPushButton(QStringLiteral("配方下发 · 未开放"));
        send->setObjectName(QStringLiteral("disabledAction"));
        send->setEnabled(false);
        send->setFixedWidth(210);
        cardLayout->addWidget(send);
        layout->addWidget(card);
        layout->addStretch();
        return page;
    }

    QWidget *makeDiagnostics()
    {
        QVBoxLayout *layout = nullptr;
        QWidget *page = pageBase(QStringLiteral("链路诊断"),
            QStringLiteral("实时 SocketCAN 报文 · 原始数据，不执行控制命令"), &layout);
        auto *stats = panel();
        auto *statsRow = new QHBoxLayout(stats);
        statsRow->setContentsMargins(15, 11, 15, 11);
        diagState_ = label(QStringLiteral("接口：检查中"), "accent");
        diagCounts_ = label(QStringLiteral("RX —    TX —"));
        statsRow->addWidget(diagState_);
        statsRow->addStretch();
        statsRow->addWidget(diagCounts_);
        layout->addWidget(stats);
        safetyQuality_ = label(QStringLiteral("采样/联锁未验收 · 等待锁定诊断 0x184（旧固件不发送）"), "warning");
        safetyQuality_->setObjectName(QStringLiteral("safetyQuality"));
        safetyQuality_->setWordWrap(true);
        layout->addWidget(safetyQuality_);
        auto *rpcCard = panel();
        auto *rpcLayout = column(rpcCard, 10, 4);
        auto *rpcActions = new QHBoxLayout;
        const QString rpcNames[] = {QStringLiteral("RPC Ping"), QStringLiteral("读状态"),
            QStringLiteral("读参数"), QStringLiteral("读诊断")};
        const std::uint32_t rpcMethods[] = {rpc_readonly::ping, rpc_readonly::status,
            rpc_readonly::params, rpc_readonly::diagnostics};
        for (int i = 0; i < 4; ++i) {
            auto *button = new QPushButton(rpcNames[i]);
            button->setObjectName(QStringLiteral("rpcReadOnlyAction"));
            button->setMinimumHeight(34);
            rpcButtons_[i] = button;
            connect(button, &QPushButton::clicked, this, [this, method = rpcMethods[i]] {
                if (!rpcCanAvailable() || motorRpc_.busy()) {
                    rpcResult_->setText(QStringLiteral("CAN 不可用；未发送 RPC")); return;
                }
                if (rpc_.begin(method, statusClock_.elapsed())) {
                    rpcRendered_ = rpc_can::State::Idle; refreshRpc();
                }
            });
            rpcActions->addWidget(button);
        }
        auto *details = new QPushButton(QStringLiteral("查看结果"));
        details->setObjectName(QStringLiteral("rpcDetails"));
        rpcDetailsButton_ = details;
        details->setMinimumHeight(34);
        connect(details, &QPushButton::clicked, this, [this] {
            if (rpcDetails_.isEmpty()) return;
            QDialog dialog(this);
            dialog.setWindowTitle(QStringLiteral("CAN RPC 只读快照"));
            dialog.resize(660, 450);
            auto *viewLayout = new QVBoxLayout(&dialog);
            auto *text = new QPlainTextEdit(rpcDetails_, &dialog);
            text->setReadOnly(true); viewLayout->addWidget(text);
            auto *close = new QPushButton(QStringLiteral("关闭"), &dialog);
            connect(close, &QPushButton::clicked, &dialog, &QDialog::accept);
            viewLayout->addWidget(close); dialog.exec();
        });
        rpcActions->addWidget(details);
        rpcLayout->addLayout(rpcActions);
        rpcResult_ = label(QStringLiteral("只读 RPC · 需 CAN RPC 固件 · 手动查询，不开放运动/参数写入"), "muted");
        rpcResult_->setObjectName(QStringLiteral("rpcReadOnlyResult"));
        rpcResult_->setTextFormat(Qt::PlainText);
        rpcResult_->setTextInteractionFlags(Qt::TextSelectableByMouse);
        rpcResult_->setMaximumHeight(84);
        rpcLayout->addWidget(rpcResult_);
        auto *historyActions = new QHBoxLayout;
        logExport_ = new QPushButton(QStringLiteral("导出 STM32 最近16条日志"));
        logExport_->setObjectName(QStringLiteral("rpcLogExport"));
        logCancel_ = new QPushButton(QStringLiteral("取消导出"));
        logCancel_->setObjectName(QStringLiteral("rpcLogCancel"));
        logExport_->setMinimumHeight(34); logCancel_->setMinimumHeight(34);
        connect(logExport_, &QPushButton::clicked, this, [this] {
            if (rpc_.busy() || motorRpc_.busy() || logDownload_.active() || !rpcCanAvailable()) return;
            const auto path = QFileDialog::getSaveFileName(this, QStringLiteral("保存 STM32 历史日志"),
                QDir::homePath()+QStringLiteral("/stm32-history-%1.log").arg(QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss")),
                QStringLiteral("日志 (*.log)"));
            if (path.isEmpty()) return;
            logExportPath_ = path;
            std::uint32_t session = QRandomGenerator::global()->generate();
            if (!session) session = 1;
            logDownload_.begin(rpc_, session, statusClock_.elapsed());
            logDownloadRendered_ = rpc_can::DownloadState::Idle; refreshLogDownload();
        });
        connect(logCancel_, &QPushButton::clicked, this, [this] { logDownload_.cancel(); });
        historyActions->addWidget(logExport_); historyActions->addWidget(logCancel_);
        rpcLayout->addLayout(historyActions);
        logExportResult_ = label(QStringLiteral("历史快照只读导出 · 实时 CAN 日志继续接收 · 完整收到后才保存文件"), "muted");
        logExportResult_->setObjectName(QStringLiteral("rpcLogExportResult"));
        logExportResult_->setTextFormat(Qt::PlainText);
        rpcLayout->addWidget(logExportResult_);
        layout->addWidget(rpcCard);
        auto *card = panel();
        auto *cardLayout = column(card, 12, 9);
        cardLayout->addWidget(label(QStringLiteral("最近接收的帧"), "section"));
        table_ = new QTableWidget(0, 4);
        table_->setHorizontalHeaderLabels({QStringLiteral("时间"), QStringLiteral("ID"),
                                           QStringLiteral("DLC"), QStringLiteral("DATA")});
        table_->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Fixed);
        table_->horizontalHeader()->resizeSection(0, 130);
        table_->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Fixed);
        table_->horizontalHeader()->resizeSection(1, 105);
        table_->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Fixed);
        table_->horizontalHeader()->resizeSection(2, 65);
        table_->horizontalHeader()->setSectionResizeMode(3, QHeaderView::Stretch);
        table_->verticalHeader()->hide();
        table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
        table_->setSelectionMode(QAbstractItemView::NoSelection);
        table_->setAlternatingRowColors(true);
        table_->setFocusPolicy(Qt::NoFocus);
        cardLayout->addWidget(table_, 1);
        layout->addWidget(card, 1);
        return page;
    }

    QWidget *makeSnapshots()
    {
        QVBoxLayout *layout = nullptr;
        QWidget *page = pageBase(QStringLiteral("诊断快照"),
            QStringLiteral("已保存的角度 / 转速 · 仅供工程分析，不是拧紧作业"), &layout);
        auto *notice = panel();
        auto *noticeLayout = column(notice, 11, 2);
        noticeLayout->addWidget(label(QStringLiteral(
            "墙上时间未校验；缺序号如实显示。无扭矩、合格判定或工单结果。"), "warning"));
        layout->addWidget(notice);

        auto *card = panel();
        auto *cardLayout = column(card, 12, 7);
        cardLayout->addWidget(label(QStringLiteral("最近 50 条快照"), "section"));
        snapshotTable_ = new QTableWidget(0, 6);
        snapshotTable_->setHorizontalHeaderLabels({QStringLiteral("编号"),
            QStringLiteral("UTC*"), QStringLiteral("样本"),
            QStringLiteral("缺序号"), QStringLiteral("时长 ms"),
            QStringLiteral("数据质量")});
        auto *header = snapshotTable_->horizontalHeader();
        const int widths[] = {65, 230, 90, 90, 100};
        for (int col = 0; col < 5; ++col) {
            header->setSectionResizeMode(col, QHeaderView::Fixed);
            header->resizeSection(col, widths[col]);
        }
        header->setSectionResizeMode(5, QHeaderView::Stretch);
        snapshotTable_->verticalHeader()->hide();
        snapshotTable_->setEditTriggers(QAbstractItemView::NoEditTriggers);
        snapshotTable_->setSelectionBehavior(QAbstractItemView::SelectRows);
        snapshotTable_->setSelectionMode(QAbstractItemView::SingleSelection);
        snapshotTable_->setAlternatingRowColors(true);
        snapshotTable_->setFocusPolicy(Qt::NoFocus);
        cardLayout->addWidget(snapshotTable_, 1);
        layout->addWidget(card, 1);

        auto *actions = panel();
        auto *row = new QHBoxLayout(actions);
        row->setContentsMargins(15, 9, 15, 9);
        auto *refresh = new QPushButton(QStringLiteral("刷新记录"));
        refresh->setObjectName(QStringLiteral("snapshotAction"));
        refresh->setFixedSize(115, 40);
        connect(refresh, &QPushButton::clicked, this, [this] { refreshSnapshots(); });
        row->addWidget(refresh);
        auto *exportButton = new QPushButton(QStringLiteral("导出选中 CSV"));
        exportButton->setObjectName(QStringLiteral("snapshotAction"));
        exportButton->setFixedSize(155, 40);
        connect(exportButton, &QPushButton::clicked, this,
                [this] { exportSelectedSnapshot(); });
        row->addWidget(exportButton);
        snapshotListResult_ = label(QStringLiteral("选择一条记录后可导出"), "muted");
        row->addWidget(snapshotListResult_, 1);
        layout->addWidget(actions);
        return page;
    }

    void refreshSnapshots()
    {
        const auto result = snapshot_store::list(snapshotDatabasePath());
        snapshotTable_->setRowCount(0);
        if (!result.ok) {
            snapshotListResult_->setText(QStringLiteral("读取失败：%1").arg(result.error));
            return;
        }
        for (const auto &capture : result.captures) {
            const int row = snapshotTable_->rowCount();
            snapshotTable_->insertRow(row);
            const QString cells[] = {
                QString::number(capture.id), capture.capturedAtUtc,
                QString::number(capture.sampleCount),
                QString::number(capture.missingSequences),
                QString::number(capture.durationMs),
                capture.missingSequences == 0 ? QStringLiteral("序号连续") :
                                                QStringLiteral("有缺序号")};
            for (int col = 0; col < 6; ++col) {
                auto *item = new QTableWidgetItem(cells[col]);
                item->setTextAlignment(Qt::AlignCenter);
                if (col == 5 && capture.missingSequences > 0)
                    item->setForeground(QColor(QStringLiteral("#ffc46b")));
                snapshotTable_->setItem(row, col, item);
            }
        }
        snapshotListResult_->setText(result.captures.isEmpty()
            ? QStringLiteral("尚无诊断快照")
            : QStringLiteral("显示 %1 条；UTC* 时钟未校验")
                  .arg(result.captures.size()));
    }

    void exportSelectedSnapshot()
    {
        const int row = snapshotTable_->currentRow();
        if (row < 0 || !snapshotTable_->item(row, 0)) {
            snapshotListResult_->setText(QStringLiteral("请先点选一条快照"));
            return;
        }
        const qint64 id = snapshotTable_->item(row, 0)->text().toLongLong();
        const auto result = snapshot_store::exportCsv(snapshotDatabasePath(), id,
                                                       snapshotExportDirectory());
        snapshotListResult_->setText(result.ok
            ? QStringLiteral("已导出 %1 点：%2")
                  .arg(result.sampleCount).arg(QFileInfo(result.path).fileName())
            : QStringLiteral("未导出：%1").arg(result.error));
    }

    void refreshStatus()
    {
        clock_->setText(QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd  HH:mm:ss")));
        const bool up = interfaceUp();
        const QString state = up ? QStringLiteral("can0 已启用") : QStringLiteral("can0 未启用");
        linkPill_->setText(state);
        linkPill_->setStyleSheet(up
            ? QStringLiteral("background:#123a35;color:#6ce6bb;border-radius:17px;font-weight:700;")
            : QStringLiteral("background:#433022;color:#ffd08e;border-radius:17px;font-weight:700;"));
        const QString rx = packetCount("rx_packets");
        const QString tx = packetCount("tx_packets");
        counts_->setText(QStringLiteral("%1 / %2").arg(rx, tx));
        diagCounts_->setText(QStringLiteral("RX %1    TX %2").arg(rx, tx));
        const auto nowMs = statusClock_.elapsed();
        const bool fresh = statusTracker_.fresh(nowMs);
        if (!safetyTracker_.fresh(nowMs)) {
            safetyQuality_->setText(safetyTracker_.seen()
                ? QStringLiteral("锁定诊断已过期 · 不授予运动权限")
                : QStringLiteral("采样/联锁未验收 · 等待 0x184（旧固件不发送）；控制锁定"));
        } else {
            const auto reasonText = [](std::uint8_t mask) {
                QStringList reasons;
                if (mask & SAMPLE_UNQUALIFIED) reasons << QStringLiteral("未标定验收");
                if (mask & SAMPLE_ACQUISITION) reasons << QStringLiteral("采集失败");
                if (mask & SAMPLE_RANGE) reasons << QStringLiteral("原码越界");
                if (mask & SAMPLE_DISAGREE) reasons << QStringLiteral("三采样不一致");
                if (mask & SAMPLE_STALE) reasons << QStringLiteral("过期");
                return reasons.isEmpty() ? QStringLiteral("诊断无异常，非安全许可") : reasons.join(QStringLiteral("/"));
            };
            const auto &quality = safetyTracker_.packet();
            QStringList missing;
            const std::pair<unsigned, const char *> items[] = {
                {SAFETY_BOOT_LOCK, "启动锁定"}, {SAFETY_ESTOP, "实体急停"},
                {SAFETY_POWER_FEEDBACK, "功率回读"}, {SAFETY_CURRENT, "电流标定"},
                {SAFETY_VBUS, "母线标定"}, {SAFETY_TEMPERATURE, "温度标定"},
                {SAFETY_ENCODER, "编码器"}, {SAFETY_LINK, "端到端链路"},
                {SAFETY_FIRMWARE, "固件确认"}, {SAFETY_RECIPE, "配方验收"},
                {SAFETY_FAULT, "故障锁存"}};
            for (const auto &item : items)
                if (quality.missing & item.first) missing << QString::fromUtf8(item.second);
            const auto rawText = [this, nowMs](unsigned channel) {
                const auto *raw = safetyRaw_.matching(channel, safetyTracker_, nowMs);
                if (!raw) return QStringLiteral("等待同序号原码");
                if (raw->raw[0] == UINT16_MAX) return QStringLiteral("采集不可用");
                return QStringLiteral("%1/%2/%3").arg(raw->raw[0]).arg(raw->raw[1]).arg(raw->raw[2]);
            };
            safetyQuality_->setText(QStringLiteral("默认锁定（缺项 0x%1）：%2\nPC4：%3；PC5：%4\n原码 #%5 · PC4 %6 · PC5 %7 · 诊断数据不授予运动权限")
                .arg(quality.missing, 3, 16, QLatin1Char('0'))
                .arg(missing.join(QStringLiteral("、")))
                .arg(reasonText(quality.pc4Reasons), reasonText(quality.pc5Reasons))
                .arg(quality.sequence).arg(rawText(0), rawText(1)));
        }
        if (!trendHistory_.empty() &&
            (!fresh || nowMs - trendHistory_.samples().back().timeMs >
                           measurement_v1::kFreshMs)) trendHistory_.clear();
        overviewTrend_->setState(fresh, nowMs);
        detailTrend_->setState(fresh, nowMs);
        if (!statusTracker_.seen()) {
            workValue_->setText(QStringLiteral("等待状态帧"));
        } else if (!fresh) {
            workValue_->setText(QStringLiteral("状态已过期"));
        } else if ((statusTracker_.packet().flags & 0x02U) != 0U) {
            workValue_->setText(QStringLiteral("故障锁存"));
        } else {
            const QString modes[] = {QStringLiteral("空闲"), QStringLiteral("位置"),
                                     QStringLiteral("速度"), QStringLiteral("电流")};
            workValue_->setText(QStringLiteral("在线 · %1").arg(modes[statusTracker_.packet().mode]));
        }
        const QString device = fresh ? QStringLiteral(" / STM32状态有效") :
            statusTracker_.seen() ? QStringLiteral(" / 状态超时") : QStringLiteral(" / 等待状态帧");
        diagState_->setText(monitor_->ready() ? state + device :
            QStringLiteral("SocketCAN 无法打开：") + monitor_->error());

        const bool motorFresh = fresh && motorTracker_.fresh(nowMs);
        const auto &motor = motorTracker_.packet();
        angleValue_->setText(motorFresh && motor.angleValid() &&
                             (statusTracker_.packet().flags & 0x04U) != 0U
            ? QStringLiteral("%1 °").arg(motor.angleMdeg / 1000.0, 0, 'f', 2)
            : QStringLiteral("— °"));
        currentValue_->setText(motorFresh && motor.currentValid() &&
                               (statusTracker_.packet().flags & 0x05U) == 0x05U
            ? QStringLiteral("%1 A").arg(motor.iqMa / 1000.0, 0, 'f', 3)
            : QStringLiteral("— A"));

        const bool electricalFresh = fresh && electricalTracker_.fresh(nowMs);
        const auto &electrical = electricalTracker_.packet();
        speedValue_->setText(electricalFresh && electrical.speedValid &&
                             (statusTracker_.packet().flags & 0x04U) != 0U
            ? QStringLiteral("%1 rpm").arg(electrical.speedDeciRpm / 10.0, 0, 'f', 1)
            : QStringLiteral("— rpm"));
        vbusValue_->setText(electricalFresh && electrical.vbusValid
            ? QStringLiteral("%1 V").arg(electrical.vbusMv / 1000.0, 0, 'f', 1)
            : QStringLiteral("— V"));

        const auto observation = preflight_observation::evaluate({
            fresh, motorTracker_.fresh(nowMs), electricalTracker_.fresh(nowMs),
            statusTracker_.packet(), motor, electrical});
        const auto show = [](QLabel *target, preflight_observation::State state,
                             const QString &pass, const QString &attention,
                             const QString &unknown) {
            using preflight_observation::State;
            target->setText(state == State::Observed ? pass :
                            state == State::Attention ? attention : unknown);
            target->setStyleSheet(state == State::Observed
                ? QStringLiteral("color:#65e3bb;font-weight:700;")
                : state == State::Attention
                    ? QStringLiteral("color:#ffc46b;font-weight:700;")
                    : QStringLiteral("color:#8c9db1;"));
        };
        show(preflightStatus_, observation.status, QStringLiteral("新鲜 ≤500 ms"),
             QStringLiteral("异常"), QStringLiteral("无新鲜状态"));
        show(preflightMode_, observation.idle, QStringLiteral("报告空闲"),
             QStringLiteral("报告非空闲"), QStringLiteral("未知"));
        show(preflightFault_, observation.softwareFaultClear,
             QStringLiteral("未报告故障"), QStringLiteral("报告故障"),
             QStringLiteral("未知"));
        show(preflightEncoder_, observation.encoderFlag,
             QStringLiteral("报告有效"), QStringLiteral("报告无效"),
             QStringLiteral("未知"));
        show(preflightAngle_, observation.angle, QStringLiteral("有效值"),
             QStringLiteral("无效值"), QStringLiteral("缺帧或序号不齐"));
        show(preflightSpeed_, observation.speed, QStringLiteral("有效值"),
             QStringLiteral("无效值"), QStringLiteral("缺帧或序号不齐"));
        show(preflightVbus_, observation.vbusEstimate, QStringLiteral("估算有效"),
             QStringLiteral("估算无效"), QStringLiteral("缺帧或序号不齐"));
        show(preflightSd_, observation.sdOutputLow,
             QStringLiteral("报告低电平"), QStringLiteral("报告高电平"),
             QStringLiteral("未知"));

        // These four inputs have no trusted live source yet. Never infer them
        // from the MCU's SD output bit or an estimated bus voltage.
        control_workflow::Evidence controlEvidence;
        controlEvidence.canUp = up;
        controlEvidence.statusFresh = fresh;
        controlEvidence.motorFresh = motorTracker_.fresh(nowMs);
        controlEvidence.electricalFresh = electricalTracker_.fresh(nowMs);
        controlEvidence.status = statusTracker_.packet();
        controlEvidence.motor = motor;
        controlEvidence.electrical = electrical;
        const auto missing = control_workflow::missing(controlEvidence);
        QStringList reasons;
        if (missing & control_workflow::CanLink) reasons << QStringLiteral("CAN 未启用");
        if (missing & control_workflow::FreshTelemetry) reasons << QStringLiteral("遥测不完整/过期");
        if (missing & control_workflow::IdleAndStationary) reasons << QStringLiteral("未证实静止空闲");
        if (missing & control_workflow::SoftwareHealthy) reasons << QStringLiteral("软件状态异常");
        if (missing & control_workflow::FirmwareControl) reasons << QStringLiteral("固件控制未验收");
        if (missing & control_workflow::EstopFeedback) reasons << QStringLiteral("缺实体急停回读");
        if (missing & control_workflow::PowerFeedback) reasons << QStringLiteral("缺功率级回读");
        if (missing & control_workflow::VerifiedRecipe) reasons << QStringLiteral("配方未验收");
        if (missing & control_workflow::VerifiedSensing) reasons << QStringLiteral("采样标定/保护未验收");
        controlGate_->setText(missing == 0U
            ? QStringLiteral("控制联锁满足；仍需执行端独立复核")
            : QStringLiteral("START 锁定：") + reasons.join(QStringLiteral("、")));
    }

    void captureSample(std::int64_t nowMs)
    {
        if (!statusTracker_.fresh(nowMs) || !motorTracker_.fresh(nowMs) ||
            !electricalTracker_.fresh(nowMs)) return;
        const auto &status = statusTracker_.packet();
        const auto &motor = motorTracker_.packet();
        const auto &electrical = electricalTracker_.packet();
        if ((status.flags & 0x06U) != 0x04U || !motor.angleValid() ||
            !electrical.speedValid || motor.sequence != status.sequence ||
            electrical.sequence != status.sequence) return;
        trendHistory_.accept({nowMs, motor.angleMdeg, electrical.speedDeciRpm,
                              status.sequence});
    }

    bool rpcCanAvailable() const { return monitor_ && monitor_->ready() && interfaceUp(); }

    void refreshMotorRpc()
    {
        if (!motorRpcQuery_ || !motorRpcResult_) return;
        motorRpcQuery_->setEnabled(!rpc_.busy() && !logDownload_.active() && !motorRpc_.busy() && rpcCanAvailable());
        const auto state = motorRpc_.state();
        if (state == motorRpcRendered_) return;
        motorRpcRendered_ = state;
        if (state == rpc_can::State::Sending || state == rpc_can::State::Waiting)
            motorRpcResult_->setText(QStringLiteral("查询电机服务中；未发送运动指令。"));
        else if (state == rpc_can::State::Success) {
            const auto& r = motorRpc_.reply();
            motorRpcResult_->setText(QStringLiteral("电机服务可达 · 控制仍锁定 · 缺项 0x%1 · 自检 0x%2 · 作业 %3 / 状态 %4 · 故障 %5 · SAFE %6\n快照不是安全许可；不会据此解锁按钮。")
                .arg(r.view.blockers, 0, 16).arg(r.view.preflight, 0, 16).arg(r.view.job_id)
                .arg(r.view.job_state).arg(r.view.fault_reason).arg(r.view.safe_latched));
        } else if (state == rpc_can::State::Timeout)
            motorRpcResult_->setText(QStringLiteral("电机服务查询超时：旧固件未注册服务或链路异常；不自动重试。"));
        else if (state == rpc_can::State::ProtocolError || state == rpc_can::State::SendError)
            motorRpcResult_->setText(QStringLiteral("电机服务响应/发送异常；不采信结果，不开放运动。"));
    }

    void refreshRpc()
    {
        if (!rpcResult_) return;
        if (rpcDetailsButton_) rpcDetailsButton_->setEnabled(!rpcDetails_.isEmpty());
        for (auto *button : rpcButtons_)
            if (button) button->setEnabled(!rpc_.busy() && !motorRpc_.busy() && !logDownload_.active() && rpcCanAvailable());
        if (rpc_.method() == rpc_readonly::logChunk) return;
        const auto state = rpc_.state();
        if (state == rpcRendered_) return;
        rpcRendered_ = state;
        if (state == rpc_can::State::Sending || state == rpc_can::State::Waiting) {
            rpcDetails_.clear();
            rpcResult_->setText(QStringLiteral("只读 RPC 请求 %1 · %2 · 不发送运动指令")
                .arg(rpc_.call()).arg(state == rpc_can::State::Sending ? QStringLiteral("节流发送中") : QStringLiteral("等待响应")));
        } else if (state == rpc_can::State::Timeout) {
            rpcResult_->setText(QStringLiteral("RPC 超时；可能未更新固件/缺片/总线异常。没有自动重发，也未执行运动控制。"));
        } else if (state == rpc_can::State::SendError) {
            rpcResult_->setText(QStringLiteral("RPC 发送失败；本次请求已终止。"));
        } else if (state == rpc_can::State::ProtocolError) {
            rpcResult_->setText(QStringLiteral("RPC 响应无效/缺片/被拒绝，状态码 %1；不采信该结果。").arg(rpc_.remoteStatus()));
        } else if (state == rpc_can::State::Success) {
            const auto word = [this](unsigned index) { return rpc_readonly::get32(rpc_.result() + index * 4U); };
            rpcDetails_ = QStringLiteral("本次只读查询成功，设备 RAM 快照；不是持续遥测，也不是安全验收。\n请求号：%1\n控制执行：未开放\n").arg(rpc_.call());
            if (rpc_.method() == rpc_readonly::ping) {
                rpcResult_->setText(QStringLiteral("RPC Ping 成功 · 响应请求号匹配 · 只读服务可达"));
                rpcDetails_ += QStringLiteral("Ping nonce 原样返回且校验一致。\n");
            } else if (rpc_.method() == rpc_readonly::status) {
                rpcResult_->setText(QStringLiteral("RPC 状态快照 · 模式 %1 · 故障码 %2 · CAN 控制锁定").arg(word(2)).arg(word(4)));
                rpcDetails_ += QStringLiteral("版本=%1\n设备tick_ms=%2\nmode=%3\nflags=%4（bit0 FOC；bit1 故障；bit2 编码器标志）\nfault=%5\nanalog_safe_latched=%6\nfw_update_active=%7\ncan_control_enabled=%8\n")
                    .arg(word(0)).arg(word(1)).arg(word(2)).arg(word(3)).arg(word(4)).arg(word(5)).arg(word(6)).arg(word(7));
            } else if (rpc_.method() == rpc_readonly::params) {
                rpcResult_->setText(QStringLiteral("RPC 已读取 18 项参数 · RUNDOWN_RPM=%1 · 查看结果可看全部；未写入").arg(word(1)));
                unsigned index = 1U;
#define RPC_DISPLAY_PARAM(field, name, low, high, initial) rpcDetails_ += QStringLiteral(name "=%1\n").arg(word(index++));
                TIGHTEN_PARAM_FIELDS(RPC_DISPLAY_PARAM)
#undef RPC_DISPLAY_PARAM
            } else {
                rpcResult_->setText(QStringLiteral("RPC 诊断 · CAN ready=%1 · Bus-off=%2 · 日志入队=%3").arg(word(6)).arg(word(7)).arg(word(2)));
                const char *names[] = {"version", "log_ready", "log_enqueued", "log_drop_full", "log_drop_uart",
                    "log_drop_pool", "can_ready", "can_bus_off", "can_recoveries", "rpc_fifo_overruns"};
                for (unsigned i = 0; i < RPC_READONLY_DIAG_WORDS; ++i)
                    rpcDetails_ += QStringLiteral("%1=%2\n").arg(QString::fromLatin1(names[i])).arg(word(i));
            }
        }
    }

    void refreshLogDownload()
    {
        if (!logExportResult_) return;
        logExport_->setEnabled(!rpc_.busy() && !motorRpc_.busy() && !logDownload_.active() && rpcCanAvailable());
        logCancel_->setEnabled(logDownload_.canCancel());
        const auto state = logDownload_.state();
        if (state == rpc_can::DownloadState::Active) {
            logExportResult_->setText(QStringLiteral("冻结历史快照读取中：%1 / %2 字节 · CAN 节流传输，可能需要数分钟")
                .arg(logDownload_.received()).arg(logDownload_.total()));
            return;
        }
        if (state == logDownloadRendered_) return;
        logDownloadRendered_ = state;
        if (state == rpc_can::DownloadState::Done) {
            QSaveFile file(logExportPath_);
            file.setDirectWriteFallback(false);
            if (!file.open(QIODevice::WriteOnly) ||
                file.write(reinterpret_cast<const char*>(logDownload_.data()), static_cast<qint64>(logDownload_.received())) !=
                    static_cast<qint64>(logDownload_.received()) || !file.commit()) {
                logExportResult_->setText(QStringLiteral("日志收齐，但文件保存失败：%1；未把部分文件当作成功。").arg(file.errorString()));
            } else {
                logExportResult_->setText(QStringLiteral("历史日志导出成功：%1 字节 · %2")
                    .arg(logDownload_.received()).arg(QFileInfo(logExportPath_).fileName()));
                logExportResult_->setToolTip(logExportPath_);
            }
        } else if (state == rpc_can::DownloadState::Cancelled) {
            logExportResult_->setText(QStringLiteral("已取消；STM32 快照引用已释放，未保存文件。"));
        } else if (state == rpc_can::DownloadState::Failed) {
            logExportResult_->setText(QStringLiteral("历史导出失败/超时，未保存部分文件；STM32 在15秒空闲超时后释放引用。"));
        }
    }

    void onFrame(const CanEntry &entry)
    {
        motorRpc_.receive(entry.rawId, entry.extended, entry.remote, entry.error,
                         static_cast<std::uint8_t>(entry.length), entry.rawData.data(), statusClock_.elapsed());
        refreshMotorRpc();
        rpc_.receive(entry.rawId, entry.extended, entry.remote, entry.error,
                     static_cast<std::uint8_t>(entry.length), entry.rawData.data(), statusClock_.elapsed());
        logDownload_.receive(entry.rawId, entry.extended, entry.remote, entry.error,
                     static_cast<std::uint8_t>(entry.length), entry.rawData.data(), statusClock_.elapsed());
        refreshRpc();
        const auto logNow = statusClock_.elapsed();
        safety_report_v1::Packet safetyPacket;
        if (safety_report_v1::decode(entry.rawId, entry.extended, entry.remote, entry.error,
                static_cast<std::uint8_t>(entry.length), entry.rawData.data(), safetyPacket) &&
            safetyTracker_.accept(safetyPacket, logNow)) refreshStatus();
        safety_report_v1::RawPacket safetyRaw;
        if (safety_report_v1::decodeRaw(entry.rawId, entry.extended, entry.remote, entry.error,
                static_cast<std::uint8_t>(entry.length), entry.rawData.data(), safetyRaw) &&
            safetyRaw_.accept(safetyRaw, logNow)) refreshStatus();
        if (entry.rawId == CAN_LOG_STATS_ID && !entry.extended && !entry.remote &&
            !entry.error && entry.length == 8 && entry.rawData[0] == 1 && entry.rawData[1] <= 8) {
            canLogStatsAt_ = logNow;
            canQueueDrop_ = entry.rawData[2] | (unsigned(entry.rawData[3]) << 8);
            canStaleDrop_ = entry.rawData[4] | (unsigned(entry.rawData[5]) << 8);
        }
        const auto complete = canLogs_.feed(entry.rawId, entry.extended, entry.remote,
            entry.error, entry.length, entry.rawData.data(), logNow);
        if (complete && logTransportIndex_ == 0) {
            if (complete->sessionStart) logs_.beginLiveSession();
            if (logs_.acceptLive(complete->text, QStringLiteral("CAN can0"))) {
                logs_.setLastLiveMs(logNow); logsDirty_ = true;
#ifdef Q_OS_LINUX
                const auto &record = logs_.entries().last().record;
                ::syslog(LOG_INFO, "PW_LOG_RX source=CAN sequence=%u tick_ms=%u level=%s tokenized=%d",
                    static_cast<unsigned>(record.sequence), static_cast<unsigned>(record.deviceTickMs),
                    record.level.c_str(), record.tokenized ? 1 : 0);
#endif
            }
        }
        CanControlV0_Reply controlReply{};
        if (CanControlV0_ParseReply(entry.rawId, entry.extended, entry.remote,
                                    entry.error, static_cast<std::uint8_t>(entry.length),
                                    entry.rawData.data(), &controlReply) != 0U) {
            controlReply_->setText(controlReply.decision == CAN_CONTROL_V0_REJECT_DISABLED
                ? QStringLiteral("收到外部 0x280：控制已禁用（序号 %1）；本机未发请求")
                      .arg(controlReply.sequence)
                : QStringLiteral("收到外部 0x280：非本机请求，不能据此认定电机动作"));
        }
        status_v1::Packet parsed;
        measurement_v1::MotorPacket motor;
        measurement_v1::ElectricalPacket electrical;
        const auto nowMs = statusClock_.elapsed();
        const bool statusWasFresh = statusTracker_.fresh(nowMs);
        if (status_v1::decode(entry.rawId, entry.extended, entry.remote,
                              entry.error, static_cast<std::uint8_t>(entry.length),
                              entry.rawData.data(), parsed) &&
            statusTracker_.accept(parsed, nowMs)) {
            if (!statusWasFresh) {
                motorTracker_.reset();
                electricalTracker_.reset();
                trendHistory_.clear();
            }
            refreshStatus();
        } else if (measurement_v1::decodeMotor(entry.rawId, entry.extended, entry.remote,
                                               entry.error, static_cast<std::uint8_t>(entry.length),
                                               entry.rawData.data(), motor) &&
                   motorTracker_.accept(motor, nowMs)) {
            captureSample(nowMs);
            refreshStatus();
        } else if (measurement_v1::decodeElectrical(entry.rawId, entry.extended, entry.remote,
                                                    entry.error, static_cast<std::uint8_t>(entry.length),
                                                    entry.rawData.data(), electrical) &&
                   electricalTracker_.accept(electrical, nowMs)) {
            captureSample(nowMs);
            refreshStatus();
        }
        latest_->setText(QStringLiteral("%1   %2\n%3").arg(entry.time, entry.id, entry.data));
        table_->insertRow(0);
        const QString cells[] = {entry.time, entry.id,
                                 QString::number(entry.length), entry.data};
        for (int i = 0; i < 4; ++i) {
            auto *item = new QTableWidgetItem(cells[i]);
            item->setTextAlignment(i == 3 ? Qt::AlignVCenter | Qt::AlignLeft : Qt::AlignCenter);
            table_->setItem(0, i, item);
        }
        if (table_->rowCount() > kMaxRows) table_->removeRow(kMaxRows);
    }

    QStackedWidget *pages_ = nullptr;
    std::vector<QPushButton *> nav_;
    QLabel *clock_ = nullptr;
    QLabel *linkPill_ = nullptr;
    QLabel *workValue_ = nullptr;
    QLabel *angleValue_ = nullptr;
    QLabel *currentValue_ = nullptr;
    QLabel *speedValue_ = nullptr;
    QLabel *vbusValue_ = nullptr;
    QLabel *counts_ = nullptr;
    QLabel *latest_ = nullptr;
    QLabel *diagState_ = nullptr;
    QLabel *diagCounts_ = nullptr;
    QLabel *preflightStatus_ = nullptr;
    QLabel *preflightMode_ = nullptr;
    QLabel *preflightFault_ = nullptr;
    QLabel *preflightEncoder_ = nullptr;
    QLabel *preflightAngle_ = nullptr;
    QLabel *preflightSpeed_ = nullptr;
    QLabel *preflightVbus_ = nullptr;
    QLabel *preflightSd_ = nullptr;
    QLabel *controlPreview_ = nullptr;
    QLabel *controlReply_ = nullptr;
    QLabel *controlGate_ = nullptr;
    QLabel *safetyQuality_ = nullptr;
    safety_report_v1::Tracker safetyTracker_;
    safety_report_v1::RawTracker safetyRaw_;
    QLabel *snapshotResult_ = nullptr;
    QLabel *snapshotListResult_ = nullptr;
    LiveTrend *overviewTrend_ = nullptr;
    LiveTrend *detailTrend_ = nullptr;
    QTableWidget *table_ = nullptr;
    QTableWidget *snapshotTable_ = nullptr;
    QTimer statusTimer_;
    QTimer rpcTimer_;
    rpc_can::Client rpc_{QRandomGenerator::global()->generate()};
    rpc_can::MotorClient motorRpc_{QRandomGenerator::global()->generate()};
    rpc_can::State motorRpcRendered_ = rpc_can::State::Idle;
    QPushButton *motorRpcQuery_ = nullptr;
    QLabel *motorRpcResult_ = nullptr;
    rpc_can::LogDownload logDownload_;
    rpc_can::DownloadState logDownloadRendered_ = rpc_can::DownloadState::Idle;
    QPushButton *logExport_ = nullptr, *logCancel_ = nullptr;
    QLabel *logExportResult_ = nullptr;
    QString logExportPath_;
    rpc_can::State rpcRendered_ = rpc_can::State::Idle;
    std::array<QPushButton *, 4> rpcButtons_{};
    QPushButton *rpcDetailsButton_ = nullptr;
    QLabel *rpcResult_ = nullptr;
    QString rpcDetails_;
    QElapsedTimer statusClock_;
    status_v1::Tracker statusTracker_;
    measurement_v1::Tracker<measurement_v1::MotorPacket> motorTracker_;
    measurement_v1::Tracker<measurement_v1::ElectricalPacket> electricalTracker_;
    telemetry_history::History trendHistory_;
    std::unique_ptr<CanMonitor> monitor_;
    std::unique_ptr<LogSerialReader> logReader_;
    log_store::Store logs_;
    QTimer logTimer_;
    int logFilterIndex_ = 0;
    int logTransportIndex_ = 0;
    std::array<QPushButton *, 4> logFilterButtons_{};
    std::array<QPushButton *, 2> logTransportButtons_{};
    can_log::Receiver canLogs_;
    qint64 canLogStatsAt_ = -1;
    unsigned canQueueDrop_ = 0, canStaleDrop_ = 0;
    QTableWidget *logTable_ = nullptr;
    QLabel *logConnection_ = nullptr;
    QLabel *logStats_ = nullptr;
    QLabel *logResult_ = nullptr;
    bool logsDirty_ = true;
    bool logPaused_ = false;
};

}  // namespace

#ifndef HMI_UI_TEST
int main(int argc, char *argv[])
{
#ifdef HAS_DRM_UI_PLANE
    QCoreApplication::setAttribute(Qt::AA_ShareOpenGLContexts);
#endif
    QApplication app(argc, argv);
    if (app.arguments().contains(QStringLiteral("--can-fd-brs")) &&
        !app.arguments().contains(QStringLiteral("--can-fd"))) return 6;
    app.setApplicationName(QStringLiteral("LubanCat Tightening HMI"));
#ifdef Q_OS_WIN
    QFontDatabase::addApplicationFont(QStringLiteral("C:/Windows/Fonts/msyh.ttc"));
    app.setFont(QFont(QStringLiteral("Microsoft YaHei"), 11));
#else
    app.setFont(QFont(QStringLiteral("Noto Sans CJK SC"), 11));
#endif
    HmiWindow window;
#ifdef HAS_DRM_UI_PLANE
    DrmUiPlane uiPlane(&app);
#endif
    const QStringList args = app.arguments();
    const int sourceArg = args.indexOf(QStringLiteral("--log-source"));
    if (sourceArg >= 0) {
        if (sourceArg + 1 >= args.size() ||
            (args[sourceArg + 1] != QStringLiteral("can") && args[sourceArg + 1] != QStringLiteral("uart"))) return 4;
        window.selectLogSource(args[sourceArg + 1] == QStringLiteral("uart"));
    }
    const int captureArg = args.indexOf(QStringLiteral("--log-capture-ms"));
    int captureMs = 0;
    if (captureArg >= 0) {
        bool valid = false;
        if (captureArg + 1 < args.size()) captureMs = args[captureArg + 1].toInt(&valid);
        if (!valid || captureMs < 1000 || captureMs > 60000) return 5;
    }
    const int pageArg = args.indexOf(QStringLiteral("--page"));
    if (pageArg >= 0 && pageArg + 1 < args.size()) {
        bool valid = false;
        const int page = args[pageArg + 1].toInt(&valid);
        if (valid && page >= 0 && page <= 7) window.activate(page);
    }
    const int logImportArg = args.indexOf(QStringLiteral("--log-import"));
    if (logImportArg >= 0 && logImportArg + 1 < args.size()) {
        if (!window.importLogFile(args[logImportArg + 1])) return 2;
    }
    const int logExportArg = args.indexOf(QStringLiteral("--log-export"));
    if (!captureMs && logExportArg >= 0 && logExportArg + 1 < args.size()) {
        if (!window.exportLogFile(args[logExportArg + 1])) return 3;
    }
    const int screenshotArg = args.indexOf(QStringLiteral("--screenshot"));
    if (screenshotArg >= 0 && screenshotArg + 1 < args.size()) {
        window.show();
        const QString path = args[screenshotArg + 1];
        QTimer::singleShot(captureMs ? captureMs : 700, &app, [&app, &window, path, args, logExportArg, captureMs] {
            if (captureMs && logExportArg >= 0 && logExportArg + 1 < args.size() &&
                !window.exportLogFile(args[logExportArg + 1])) { app.exit(3); return; }
            if (!window.grab().save(path)) qWarning("Cannot save screenshot");
            app.quit();
        });
    } else if (args.contains(QStringLiteral("--windowed"))) {
        window.show();
    } else {
        window.showFullScreen();
#ifdef HAS_DRM_UI_PLANE
        if (qEnvironmentVariableIsSet("QT_QPA_PLATFORM") &&
            qgetenv("QT_QPA_PLATFORM") == "eglfs") {
            QTimer::singleShot(0, &window, [&window, &uiPlane] {
                if (uiPlane.start()) {
                    uiPlane.setTarget(&window);
                } else {
                    qWarning("Failed to start DRM UI plane");
                }
            });
        }
#endif
    }
    if (captureMs && screenshotArg < 0) {
        QTimer::singleShot(captureMs, &app, [&app, &window, args, logExportArg] {
            if (logExportArg >= 0 && logExportArg + 1 < args.size() &&
                !window.exportLogFile(args[logExportArg + 1])) { app.exit(3); return; }
            app.quit();
        });
    }
    return app.exec();
}
#endif
