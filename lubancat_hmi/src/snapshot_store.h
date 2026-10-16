#pragma once

#include "telemetry_history.h"

#include <QDateTime>
#include <QString>
#include <QVector>

#include <deque>

namespace snapshot_store {

struct Result {
    bool ok = false;
    qint64 captureId = 0;
    int sampleCount = 0;
    int missingSequences = 0;
    QString error;
};

// A diagnostic measurement snapshot, never a tightening job or pass/fail result.
// The wall clock is stored as unverified until time synchronization is audited.
Result save(const QString &databasePath,
            const std::deque<telemetry_history::Sample> &samples,
            const QDateTime &capturedAtUtc);

struct CaptureSummary {
    qint64 id = 0;
    QString capturedAtUtc;
    bool clockVerified = false;
    int sampleCount = 0;
    int missingSequences = 0;
    qint64 durationMs = 0;
};

struct ListResult {
    bool ok = false;
    QVector<CaptureSummary> captures;
    QString error;
};

// Listing never creates a database. Most recent captures first, at most 100.
ListResult list(const QString &databasePath, int limit = 50);

struct ExportResult {
    bool ok = false;
    QString path;
    int sampleCount = 0;
    QString error;
};

// Atomic CSV export. Existing files are never overwritten.
ExportResult exportCsv(const QString &databasePath, qint64 captureId,
                       const QString &exportDirectory);

}  // namespace snapshot_store
