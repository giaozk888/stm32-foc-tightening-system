#define HMI_UI_TEST 1
#include "../src/main.cpp"
#include <QTemporaryDir>
#include <QThread>
#include <QScrollBar>
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include "../../tests/can_rpc_host/test_assert.h"

int main(int argc, char **argv)
{
    qputenv("QT_QPA_PLATFORM", "offscreen");
    qputenv("LUBANCAT_HMI_LOG_PORT", "");
    QTemporaryDir records;
    assert(records.isValid());
    qputenv("LUBANCAT_HMI_RECORD_DB", (records.path() + "/test.sqlite").toUtf8());
    QApplication app(argc, argv);
#ifdef Q_OS_WIN
    assert(QFontDatabase::addApplicationFont(QStringLiteral("C:/Windows/Fonts/msyh.ttc")) >= 0);
    app.setFont(QFont(QStringLiteral("Microsoft YaHei"), 11));
#else
    app.setFont(QFont(QStringLiteral("Noto Sans CJK SC"), 11));
#endif
    HmiWindow window;
    auto *motorQuery = window.findChild<QPushButton *>(QStringLiteral("motorRpcQuery"));
    assert(motorQuery && !motorQuery->isEnabled());
    assert(window.findChild<QLabel *>(QStringLiteral("motorRpcResult")));
    for (auto *button : window.findChildren<QPushButton *>(QStringLiteral("disabledAction")))
        assert(!button->isEnabled());
    assert(window.findChildren<QPushButton *>(QStringLiteral("rpcReadOnlyAction")).size() == 4);
    auto *exportButton = window.findChild<QPushButton *>(QStringLiteral("rpcLogExport"));
    auto *cancelButton = window.findChild<QPushButton *>(QStringLiteral("rpcLogCancel"));
    assert(exportButton && cancelButton && !exportButton->isEnabled() && !cancelButton->isEnabled());
    window.activate(5);
    window.show(); app.processEvents();
    auto *quality = window.findChild<QLabel *>(QStringLiteral("safetyQuality"));
    assert(quality && quality->text().contains(QStringLiteral("等待 0x184")));
    CanEntry entry;
    entry.length = 8; entry.rawId = 0x184;
    entry.rawData = {1, 3, 0xff, 7, 0x1f, 0x1f, 0, 0};
    window.injectTestFrame(entry);
    assert(quality->text().contains(QStringLiteral("实体急停")));
    assert(quality->text().contains(QStringLiteral("三采样不一致")));
    assert(quality->text().contains(QStringLiteral("未标定验收")));
    entry.rawId = 0x185;
    entry.rawData = {0x58, 2, 0x59, 2, 0x5a, 2, 0, 0};
    window.injectTestFrame(entry);
    assert(quality->text().contains("600/601/602"));
    entry.rawId = 0x186;
    entry.rawData = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0, 0};
    window.injectTestFrame(entry);
    assert(quality->text().contains(QStringLiteral("采集不可用")));
    app.processEvents();
    const auto position = quality->mapTo(&window, QPoint(0, 0));
    assert(position.y() >= 0 && position.y() + quality->height() <= window.height());
    assert(quality->height() >= quality->heightForWidth(quality->width()));
    auto *exportLabel = window.findChild<QLabel *>(QStringLiteral("rpcLogExportResult"));
    assert(exportLabel);
    const auto exportPos = exportLabel->mapTo(&window,QPoint(0,0));
    assert(exportPos.y() >= 0 && exportPos.y()+exportLabel->height() <= window.height());
    assert(window.grab().save(QStringLiteral("safety-diag-offline.png")));
    window.activate(2); app.processEvents();
    bool sensingGate = false;
    for (auto *item : window.findChildren<QLabel *>())
        sensingGate |= item->text().contains(QStringLiteral("采样标定/保护未验收"));
    assert(sensingGate);
    auto *motorGate = window.findChild<QLabel *>(QStringLiteral("motorControlGate"));
    assert(motorGate && motorGate->height() >= motorGate->heightForWidth(motorGate->width()));
    assert(motorQuery->height() >= 36);
    assert(window.grab().save(QStringLiteral("safety-control-offline.png")));
    auto *controlScroll = window.findChild<QScrollArea *>(QStringLiteral("motorControlScroll"));
    assert(controlScroll);
    controlScroll->verticalScrollBar()->setValue(controlScroll->verticalScrollBar()->maximum());
    app.processEvents();
    assert(window.grab().save(QStringLiteral("safety-control-bottom-offline.png")));
    QThread::msleep(510);
    window.refreshTestStatus();
    assert(quality->text().contains(QStringLiteral("已过期")));
}
