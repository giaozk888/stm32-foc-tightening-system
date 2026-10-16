#include "snapshot_store.h"

#include <QCoreApplication>
#include <QFile>
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QVariant>

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTemporaryDir directory;
    assert(directory.isValid());
    const QString path = directory.path() + QStringLiteral("/nested/telemetry.sqlite3");
    const auto emptyList = snapshot_store::list(path);
    assert(emptyList.ok && emptyList.captures.isEmpty());
    assert(!QFile::exists(path)); // Browsing must not create an empty database.
    const auto timestamp = QDateTime::fromString(QStringLiteral("2026-09-29T05:00:00Z"),
                                                  Qt::ISODate);
    assert(!snapshot_store::save(path, {}, timestamp).ok);
    std::deque<telemetry_history::Sample> points = {
        {1000, -1500, 12, 65535},
        {1100, -1400, 15, 0},
        {1200, -1300, 18, 2},
    };
    const auto saved = snapshot_store::save(path, points, timestamp);
    assert(saved.ok);
    assert(saved.captureId == 1);
    assert(saved.sampleCount == 3);
    assert(saved.missingSequences == 1);
    const auto captures = snapshot_store::list(path);
    assert(captures.ok && captures.captures.size() == 1);
    assert(captures.captures.front().id == saved.captureId);
    assert(captures.captures.front().sampleCount == 3);
    assert(captures.captures.front().missingSequences == 1);
    assert(!captures.captures.front().clockVerified);
    const QString exportDir = directory.path() + QStringLiteral("/exports");
    const auto csv = snapshot_store::exportCsv(path, saved.captureId, exportDir);
    assert(csv.ok && csv.sampleCount == 3);
    QFile exported(csv.path);
    assert(exported.open(QIODevice::ReadOnly));
    const QByteArray contents = exported.readAll();
    exported.close();
    assert(contents.startsWith("kind,capture_id,captured_at_utc,clock_verified,"));
    assert(contents.contains("diagnostic_read_only,1,2026-09-29T05:00:00.000Z,0,3,1,200,"));
    assert(contents.contains(",0,0,65535,-1500,12\n"));
    assert(contents.contains(",2,200,2,-1300,18\n"));
    assert(contents.count('\n') == 4);
    assert(!snapshot_store::exportCsv(path, saved.captureId, exportDir).ok);
    assert(!snapshot_store::exportCsv(path, 999, exportDir).ok);

    {
        QSqlDatabase db = QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"),
                                                     QStringLiteral("verify"));
        db.setDatabaseName(path);
        assert(db.open());
        QSqlQuery query(db);
        assert(query.exec(QStringLiteral(
            "SELECT kind, clock_verified, sample_count, missing_sequences, duration_ms "
            "FROM captures")));
        assert(query.next());
        assert(query.value(0).toString() == QStringLiteral("diagnostic_read_only"));
        assert(query.value(1).toInt() == 0);
        assert(query.value(2).toInt() == 3);
        assert(query.value(3).toInt() == 1);
        assert(query.value(4).toInt() == 200);
        assert(!query.next());
        assert(query.exec(QStringLiteral(
            "SELECT elapsed_ms, sequence, angle_mdeg, speed_deci_rpm "
            "FROM capture_samples ORDER BY sample_index")));
        assert(query.next());
        assert(query.value(0).toInt() == 0);
        assert(query.value(1).toInt() == 65535);
        assert(query.value(2).toInt() == -1500);
        assert(query.value(3).toInt() == 12);
        assert(query.next());
        assert(query.next());
        assert(query.value(0).toInt() == 200);
        assert(query.value(1).toInt() == 2);
        assert(!query.next());
        query.finish();
        db.close();
    }
    QSqlDatabase::removeDatabase(QStringLiteral("verify"));

    points[2].timeMs = 900;
    assert(!snapshot_store::save(path, points, timestamp).ok);

    {
        QSqlDatabase db = QSqlDatabase::addDatabase(QStringLiteral("QSQLITE"),
                                                     QStringLiteral("corrupt-test"));
        db.setDatabaseName(path);
        assert(db.open());
        QSqlQuery query(db);
        assert(query.exec(QStringLiteral("UPDATE captures SET sample_count=4 WHERE id=1")));
        query.finish();
        db.close();
    }
    QSqlDatabase::removeDatabase(QStringLiteral("corrupt-test"));
    const QString badExportDir = directory.path() + QStringLiteral("/bad-export");
    const auto bad = snapshot_store::exportCsv(path, saved.captureId, badExportDir);
    assert(!bad.ok);
    assert(!QFile::exists(bad.path));
    return 0;
}
