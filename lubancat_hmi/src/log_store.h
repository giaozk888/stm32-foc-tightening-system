#pragma once

#include "pigweed_log.h"
#include <QDateTime>
#include <QString>
#include <QVector>

namespace log_store {

struct Entry {
    pigweed_log::Record record;
    QString source;
    QString receivedAtUtc;
    quint64 session = 0;
    bool imported = false;
};

class Store {
public:
    void beginLiveSession() { live_.beginSession(); }
    bool acceptLive(const std::string &line, const QString &source);
    bool importText(const QString &path, QString &result);
    bool exportJsonl(const QString &directory, QString &result) const;
    const QVector<Entry> &entries() const { return entries_; }
    quint64 missing() const { return live_.missing() + importedMissing_; }
    quint64 evicted() const { return evicted_; }
    quint64 ignored() const { return ignored_; }
    qint64 lastLiveMs() const { return lastLiveMs_; }
    void setLastLiveMs(qint64 time) { lastLiveMs_ = time; }

private:
    void append(const pigweed_log::Record &record, const QString &source,
                quint64 session, bool imported);
    pigweed_log::Buffer live_{1U};
    QVector<Entry> entries_;
    quint64 importedMissing_ = 0;
    quint64 importSession_ = 0;
    quint64 evicted_ = 0;
    quint64 ignored_ = 0;
    qint64 lastLiveMs_ = -1;
};

} // namespace log_store
