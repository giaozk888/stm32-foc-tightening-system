// Linux pseudo-terminal integration test, not a real STM32 acceptance test.
#include "log_serial_reader.h"
#include "log_store.h"
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QThread>
#include <cstdlib>
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

template<typename Predicate>
bool waitFor(Predicate done)
{
    QElapsedTimer time;
    time.start();
    while (!done() && time.elapsed() < 4000) {
        QCoreApplication::processEvents();
        QThread::msleep(5);
    }
    return done();
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    const int master = ::posix_openpt(O_RDWR | O_NOCTTY | O_NONBLOCK);
    assert(master >= 0 && ::grantpt(master) == 0 && ::unlockpt(master) == 0);
    const QString path = QString::fromLocal8Bit(::ptsname(master));
    log_store::Store store;
    int sessions = 0;
    LogSerialReader reader(path,
        [&](const std::string &line) { store.acceptLive(line, path); },
        [&] { ++sessions; store.beginLiveSession(); });
    assert(waitFor([&] { return reader.connected(); }));
    const std::string first = "[PW][1][10ms][INFO][TEST] synth";
    assert(::write(master, first.data(), first.size()) == static_cast<ssize_t>(first.size()));
    QCoreApplication::processEvents();
    assert(store.entries().isEmpty()); // A fragment is not a complete record.
    const std::string next = "etic\r\n[PW][3][20ms][WARN][TEST] synthetic gap\n";
    assert(::write(master, next.data(), next.size()) == static_cast<ssize_t>(next.size()));
    assert(waitFor([&] { return store.entries().size() == 2; }));
    assert(store.entries().first().record.message == "synthetic");
    assert(store.missing() == 1U);
    char command[64];
    // No echo and no writes/commands from the HMI receiver.
    assert(::read(master, command, sizeof(command)) < 0 && errno == EAGAIN);
    reader.reconnect();
    assert(waitFor([&] { return reader.connected() && sessions == 2; }));
    const std::string reboot = "[PW][1][1ms][INFO][TEST] synthetic new session\n";
    assert(::write(master, reboot.data(), reboot.size()) == static_cast<ssize_t>(reboot.size()));
    assert(waitFor([&] { return store.entries().size() == 3; }));
    assert(store.entries().last().session == 2U);
    ::close(master);
    assert(waitFor([&] { return !reader.connected(); }));
}
