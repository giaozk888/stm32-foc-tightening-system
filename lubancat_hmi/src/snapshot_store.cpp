#include "snapshot_store.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QSqlDatabase>
#include <QSqlError>
#include <QSqlQuery>
#include <QStringList>
#include <QVariant>
#include <QUuid>

namespace snapshot_store {
namespace {

bool execute(QSqlDatabase &db, const QString &statement, QString &error)
{
    QSqlQuery query(db);
    if (query.exec(statement)) return true;
    error = query.lastError().text();
    return false;
}

class ReadConnection {
public:
    explicit ReadConnection(const QString &path)
        : name_(QStringLiteral("snapshot-read-") +
                QUuid::createUuid().toString(QUuid::WithoutBraces)),
          db_(QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"), name_))
    {
        db_.setConnectOptions(QStringLiteral("QSQLITE_OPEN_READONLY"));
        db_.setDatabaseName(path);
    }

    ~ReadConnection()
    {
        db_.close();
        db_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(name_);
    }

    QSqlDatabase &database() { return db_; }

private:
    QString name_;
    QSqlDatabase db_;
};

}  // namespace

Result save(const QString &databasePath,
            const std::deque<telemetry_history::Sample> &samples,
            const QDateTime &capturedAtUtc)
{
    Result result;
    if (samples.size() < 2 || samples.size() > telemetry_history::kMaxSamples ||
        !capturedAtUtc.isValid() || databasePath.isEmpty()) {
        result.error = QStringLiteral("需要 2–600 个有效样本、有效时间和数据库路径");
        return result;
    }
    for (std::size_t i = 1; i < samples.size(); ++i) {
        if (samples[i].timeMs < samples[i - 1].timeMs ||
            !measurement_v1::sequenceForward(samples[i].sequence,
                                             samples[i - 1].sequence)) {
            result.error = QStringLiteral("样本时间或序号顺序无效");
            return result;
        }
        const auto delta = static_cast<std::uint16_t>(samples[i].sequence -
                                                       samples[i - 1].sequence);
        result.missingSequences += delta - 1;
    }
    const auto duration = samples.back().timeMs - samples.front().timeMs;
    if (duration < 0 || duration > telemetry_history::kWindowMs) {
        result.error = QStringLiteral("样本超出 30 秒窗口");
        return result;
    }
    const QFileInfo target(databasePath);
    if (!QDir().mkpath(target.absolutePath())) {
        result.error = QStringLiteral("无法创建记录目录");
        return result;
    }

    const QString connection = QStringLiteral("snapshot-") +
                               QUuid::createUuid().toString(QUuid::WithoutBraces);
    {
        QSqlDatabase db = QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"), connection);
        db.setDatabaseName(databasePath);
        if (!db.open()) {
            result.error = db.lastError().text();
        } else {
            QString error;
            const bool schemaReady =
                execute(db, QStringLiteral("PRAGMA foreign_keys=ON"), error) &&
                execute(db, QStringLiteral("PRAGMA busy_timeout=3000"), error) &&
                execute(db, QStringLiteral(
                    "CREATE TABLE IF NOT EXISTS captures ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "captured_at_utc TEXT NOT NULL, clock_verified INTEGER NOT NULL CHECK(clock_verified=0), "
                    "kind TEXT NOT NULL CHECK(kind='diagnostic_read_only'), "
                    "sample_count INTEGER NOT NULL, missing_sequences INTEGER NOT NULL, "
                    "duration_ms INTEGER NOT NULL)"), error) &&
                execute(db, QStringLiteral(
                    "CREATE TABLE IF NOT EXISTS capture_samples ("
                    "capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE, "
                    "sample_index INTEGER NOT NULL, elapsed_ms INTEGER NOT NULL, "
                    "sequence INTEGER NOT NULL, angle_mdeg INTEGER NOT NULL, "
                    "speed_deci_rpm INTEGER NOT NULL, "
                    "PRIMARY KEY(capture_id, sample_index))"), error);
            if (!schemaReady) {
                result.error = error;
            } else if (!db.transaction()) {
                result.error = db.lastError().text();
            } else {
                QSqlQuery capture(db);
                capture.prepare(QStringLiteral(
                    "INSERT INTO captures (captured_at_utc, clock_verified, kind, "
                    "sample_count, missing_sequences, duration_ms) "
                    "VALUES (?, 0, 'diagnostic_read_only', ?, ?, ?)"));
                capture.addBindValue(capturedAtUtc.toUTC().toString(Qt::ISODateWithMs));
                capture.addBindValue(static_cast<int>(samples.size()));
                capture.addBindValue(result.missingSequences);
                capture.addBindValue(static_cast<qlonglong>(duration));
                if (!capture.exec()) {
                    result.error = capture.lastError().text();
                    db.rollback();
                } else {
                    const qint64 id = capture.lastInsertId().toLongLong();
                    QSqlQuery sample(db);
                    sample.prepare(QStringLiteral(
                        "INSERT INTO capture_samples (capture_id, sample_index, elapsed_ms, "
                        "sequence, angle_mdeg, speed_deci_rpm) VALUES (?, ?, ?, ?, ?, ?)"));
                    bool complete = true;
                    for (std::size_t i = 0; i < samples.size(); ++i) {
                        const auto &point = samples[i];
                        sample.bindValue(0, id);
                        sample.bindValue(1, static_cast<int>(i));
                        sample.bindValue(2, static_cast<qlonglong>(point.timeMs -
                                                                  samples.front().timeMs));
                        sample.bindValue(3, point.sequence);
                        sample.bindValue(4, point.angleMdeg);
                        sample.bindValue(5, point.speedDeciRpm);
                        if (!sample.exec()) {
                            result.error = sample.lastError().text();
                            complete = false;
                            break;
                        }
                    }
                    if (!complete) {
                        db.rollback();
                    } else if (!db.commit()) {
                        result.error = db.lastError().text();
                        db.rollback();
                    } else {
                        result.ok = true;
                        result.captureId = id;
                        result.sampleCount = static_cast<int>(samples.size());
                    }
                }
            }
        }
        db.close();
    }
    QSqlDatabase::removeDatabase(connection);
    return result;
}

ListResult list(const QString &databasePath, int limit)
{
    ListResult result;
    if (databasePath.isEmpty() || limit < 1 || limit > 100) {
        result.error = QStringLiteral("数据库路径或记录数量无效");
        return result;
    }
    if (!QFileInfo::exists(databasePath)) {
        result.ok = true;
        return result;
    }
    ReadConnection connection(databasePath);
    auto &db = connection.database();
    if (!db.open()) {
        result.error = db.lastError().text();
        return result;
    }
    QSqlQuery query(db);
    query.prepare(QStringLiteral(
        "SELECT id, captured_at_utc, clock_verified, sample_count, "
        "missing_sequences, duration_ms FROM captures "
        "WHERE kind='diagnostic_read_only' ORDER BY id DESC LIMIT ?"));
    query.addBindValue(limit);
    if (!query.exec()) {
        result.error = query.lastError().text();
        return result;
    }
    while (query.next()) {
        CaptureSummary capture;
        capture.id = query.value(0).toLongLong();
        capture.capturedAtUtc = query.value(1).toString();
        capture.clockVerified = query.value(2).toBool();
        capture.sampleCount = query.value(3).toInt();
        capture.missingSequences = query.value(4).toInt();
        capture.durationMs = query.value(5).toLongLong();
        result.captures.push_back(capture);
    }
    result.ok = true;
    return result;
}

ExportResult exportCsv(const QString &databasePath, qint64 captureId,
                       const QString &exportDirectory)
{
    ExportResult result;
    if (databasePath.isEmpty() || captureId <= 0 || exportDirectory.isEmpty() ||
        !QFileInfo::exists(databasePath)) {
        result.error = QStringLiteral("数据库、快照编号或导出目录无效");
        return result;
    }
    ReadConnection connection(databasePath);
    auto &db = connection.database();
    if (!db.open()) {
        result.error = db.lastError().text();
        return result;
    }
    CaptureSummary capture;
    {
        QSqlQuery query(db);
        query.prepare(QStringLiteral(
            "SELECT id, captured_at_utc, clock_verified, sample_count, "
            "missing_sequences, duration_ms FROM captures "
            "WHERE id=? AND kind='diagnostic_read_only'"));
        query.addBindValue(captureId);
        if (!query.exec()) {
            result.error = query.lastError().text();
            return result;
        }
        if (!query.next()) {
            result.error = QStringLiteral("找不到这条只读诊断快照");
            return result;
        }
        capture.id = query.value(0).toLongLong();
        capture.capturedAtUtc = query.value(1).toString();
        capture.clockVerified = query.value(2).toBool();
        capture.sampleCount = query.value(3).toInt();
        capture.missingSequences = query.value(4).toInt();
        capture.durationMs = query.value(5).toLongLong();
    }
    if (!QDir().mkpath(exportDirectory)) {
        result.error = QStringLiteral("无法创建导出目录");
        return result;
    }
    result.path = QDir(exportDirectory).filePath(
        QStringLiteral("capture-%1.csv").arg(capture.id));
    if (QFile::exists(result.path)) {
        result.error = QStringLiteral("导出文件已存在，不覆盖：") + result.path;
        return result;
    }
    QSqlQuery query(db);
    query.prepare(QStringLiteral(
        "SELECT sample_index, elapsed_ms, sequence, angle_mdeg, speed_deci_rpm "
        "FROM capture_samples WHERE capture_id=? ORDER BY sample_index"));
    query.addBindValue(capture.id);
    if (!query.exec()) {
        result.error = query.lastError().text();
        return result;
    }

    QSaveFile file(result.path);
    if (!file.open(QIODevice::WriteOnly)) {
        result.error = file.errorString();
        return result;
    }
    const QByteArray header =
        "kind,capture_id,captured_at_utc,clock_verified,sample_count,"
        "missing_sequences,duration_ms,sample_index,elapsed_ms,sequence,"
        "angle_mdeg,speed_deci_rpm\n";
    if (file.write(header) != header.size()) {
        result.error = file.errorString();
        file.cancelWriting();
        return result;
    }
    while (query.next()) {
        const QStringList fields = {
            QStringLiteral("diagnostic_read_only"),
            QString::number(capture.id), capture.capturedAtUtc,
            QString::number(capture.clockVerified ? 1 : 0),
            QString::number(capture.sampleCount),
            QString::number(capture.missingSequences),
            QString::number(capture.durationMs),
            query.value(0).toString(), query.value(1).toString(),
            query.value(2).toString(), query.value(3).toString(),
            query.value(4).toString()};
        const QByteArray line = (fields.join(QLatin1Char(',')) + QLatin1Char('\n')).toUtf8();
        if (file.write(line) != line.size()) {
            result.error = file.errorString();
            file.cancelWriting();
            return result;
        }
        ++result.sampleCount;
    }
    if (result.sampleCount != capture.sampleCount) {
        result.error = QStringLiteral("样本数量与记录头不一致，已取消导出");
        file.cancelWriting();
        return result;
    }
    if (!file.commit()) {
        result.error = file.errorString();
        return result;
    }
    result.ok = true;
    return result;
}

}  // namespace snapshot_store
