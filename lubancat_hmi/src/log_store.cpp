#include "log_store.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QUuid>

namespace log_store {

void Store::append(const pigweed_log::Record &record, const QString &source,
                   quint64 session, bool imported)
{
    if (entries_.size() >= 300) { entries_.removeFirst(); ++evicted_; }
    entries_.append({record, source,
                     QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs),
                     session, imported});
}

bool Store::acceptLive(const std::string &line, const QString &source)
{
    pigweed_log::Record record;
    if (!pigweed_log::parse(line, record) || !live_.append(record)) {
        ++ignored_;
        return false;
    }
    append(record, source, live_.sessions(), false);
    return true;
}

bool Store::importText(const QString &path, QString &result)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) { result = file.errorString(); return false; }
    if (file.size() > 2 * 1024 * 1024) {
        result = QStringLiteral("日志文件超过 2 MiB，请先截取需要的片段");
        return false;
    }
    pigweed_log::Buffer imported(300U);
    pigweed_log::Lines framer;
    quint64 skipped = 0;
    const auto parseLine = [&](const std::string &line) {
        pigweed_log::Record record;
        if (!pigweed_log::parse(line, record) || !imported.append(record)) ++skipped;
    };
    while (!file.atEnd()) {
        const auto bytes = file.read(4096);
        if (bytes.isEmpty() && file.error() != QFile::NoError) {
            result = file.errorString(); return false;
        }
        for (const auto &line : framer.feed({bytes.constData(),
                                           static_cast<std::size_t>(bytes.size())}))
            parseLine(line);
    }
    for (const auto &line : framer.feed("\n")) if (!line.empty()) parseLine(line);
    if (imported.records().empty()) {
        result = QStringLiteral("没有合法 [PW] / [PWT] 日志记录");
        return false;
    }
    ++importSession_;
    for (const auto &record : imported.records())
        append(record, QFileInfo(path).fileName(), importSession_, true);
    importedMissing_ += imported.missing();
    evicted_ += imported.evicted();
    ignored_ += skipped + framer.oversized();
    result = QStringLiteral("已导入 %1 条历史日志：%2；跳过 %3 条")
                 .arg(imported.records().size()).arg(QFileInfo(path).fileName())
                 .arg(skipped + framer.oversized());
    return true;
}

bool Store::exportJsonl(const QString &directory, QString &result) const
{
    if (entries_.isEmpty()) { result = QStringLiteral("暂无可导出的日志"); return false; }
    if (!QDir().mkpath(directory)) { result = QStringLiteral("无法创建导出目录"); return false; }
    const auto path = QDir(directory).filePath(QStringLiteral("pigweed-%1-%2.jsonl")
        .arg(QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMdd-HHmmss")),
             QUuid::createUuid().toString(QUuid::WithoutBraces)));
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly)) { result = file.errorString(); return false; }
    auto write = [&](const QJsonObject &object) {
        const auto bytes = QJsonDocument(object).toJson(QJsonDocument::Compact) + '\n';
        return file.write(bytes) == bytes.size();
    };
    if (!write({{"kind", "pigweed_capture"}, {"schema", 1}, {"clock_verified", false},
                {"count", entries_.size()}, {"missing_sequences", qint64(missing())},
                {"cache_evicted", qint64(evicted_)}, {"ignored_lines", qint64(ignored_)}})) {
        result = file.errorString(); return false;
    }
    for (const auto &entry : entries_) {
        const auto &r = entry.record;
        if (!write({{"kind", "pigweed_log"}, {"source", entry.source},
                    {"session", qint64(entry.session)}, {"imported", entry.imported},
                    {"received_at_utc", entry.receivedAtUtc}, {"clock_verified", false},
                    {"sequence", qint64(r.sequence)}, {"device_tick_ms", qint64(r.deviceTickMs)},
                    {"level", QString::fromStdString(r.level)},
                    {"module", QString::fromStdString(r.module)},
                    {"message", QString::fromStdString(r.message)}, {"tokenized", r.tokenized},
                    {"token_metadata", QString::fromStdString(r.tokenMetadata)},
                    {"token_bytes", qint64(r.tokenBytes)}, {"raw", QString::fromStdString(r.raw)}})) {
            result = file.errorString(); return false;
        }
    }
    if (!file.commit()) { result = file.errorString(); return false; }
    result = path;
    return true;
}

} // namespace log_store
