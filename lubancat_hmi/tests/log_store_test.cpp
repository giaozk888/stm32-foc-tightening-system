#include "log_store.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTemporaryDir directory;
    assert(directory.isValid());
    log_store::Store store;
    QString result;
    assert(store.importText(QStringLiteral(LOG_FIXTURE), result));
    assert(store.entries().size() == 16);
    assert(store.entries().first().record.sequence == 8U);
    assert(store.entries().last().record.sequence == 23U);
    assert(store.entries().first().imported);
    assert(store.missing() == 0U);
    store.beginLiveSession();
    assert(store.acceptLive("[PW][1][10ms][WARN][A] \"quoted\" value", "/dev/test"));
    assert(!store.acceptLive("[PW][1][10ms][WARN][A] duplicate", "/dev/test"));
    assert(store.acceptLive("[PW][3][20ms][INFO][A] next", "/dev/test"));
    assert(store.missing() == 1U);
    assert(store.exportJsonl(directory.path(), result));
    QFile exported(result);
    assert(exported.open(QIODevice::ReadOnly));
    auto header = QJsonDocument::fromJson(exported.readLine()).object();
    assert(header["count"].toInt() == 18);
    assert(header["clock_verified"].toBool() == false);
    int entries = 0;
    while (!exported.atEnd()) {
        const auto item = QJsonDocument::fromJson(exported.readLine()).object();
        assert(item["kind"].toString() == "pigweed_log");
        assert(!item["raw"].toString().isEmpty());
        if (++entries == 17) assert(item["message"].toString() == "\"quoted\" value");
    }
    assert(entries == 18);
    const auto firstPath = result;
    assert(store.exportJsonl(directory.path(), result));
    assert(result != firstPath && QFile::exists(firstPath));
    QFile empty(directory.filePath("empty.log"));
    assert(empty.open(QIODevice::WriteOnly));
    empty.close();
    const int before = store.entries().size();
    assert(!store.importText(empty.fileName(), result));
    assert(store.entries().size() == before);
}
