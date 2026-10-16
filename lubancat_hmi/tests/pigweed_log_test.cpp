#include "pigweed_log.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main()
{
    pigweed_log::Record record;
    assert(pigweed_log::parse("[PW][42][1234ms][WARN][MOTOR] speed low\r\n", record));
    assert(record.sequence == 42U && record.deviceTickMs == 1234U);
    assert(record.level == "WARN" && record.module == "MOTOR");
    assert(record.message == "speed low" && !record.tokenized);
    assert(pigweed_log::parse("[PWT][43][1240ms][INFO][M=00000002][B=4] $AQIDBA==", record));
    assert(record.tokenized && record.tokenMetadata == "00000002");
    assert(record.tokenBytes == 4U && record.message == "$AQIDBA==");
    assert(!pigweed_log::parse("[PWT][44][1241ms][INFO][M=00000002][B=0] $AQID", record));
    assert(!pigweed_log::parse("[PWT][44][1241ms][INFO][M=00000002][B=5] $AQIDBA==", record));
    assert(!pigweed_log::parse("[PWT][44][1241ms][INFO][M=00000002][B=4] $AQ=DBA==", record));
    assert(!pigweed_log::parse("[PWT][44][1241ms][INFO][M=00000002][B=4] $AQIDBAAA", record));
    assert(!pigweed_log::parse("[PW][45][12ms][INFO][A] x\nINJECT", record));
    assert(!pigweed_log::parse("1400 OK STATUS STAGE=0", record));
    assert(!pigweed_log::parse("[PW][4294967296][1ms][INFO][A] overflow", record));

    pigweed_log::Buffer buffer(2U);
    pigweed_log::Record first{1U, 10U, "INFO", "A", "first"};
    pigweed_log::Record third{3U, 30U, "INFO", "A", "third"};
    pigweed_log::Record reboot{1U, 1U, "INFO", "A", "reboot"};
    assert(buffer.append(first));
    assert(!buffer.append(first));
    assert(buffer.append(third));
    assert(buffer.missing() == 1U);
    assert(!buffer.append(first)); // Old dump is not a new live entry.
    assert(!buffer.append(reboot)); // Lower sequence is ambiguous until reconnect.
    buffer.beginSession();
    assert(buffer.append(reboot));
    assert(buffer.sessions() == 1U && buffer.evicted() == 1U);
    assert(buffer.records().size() == 2U);
    pigweed_log::Lines stream;
    assert(stream.feed("[PW][1][2ms][INFO]").empty());
    auto lines = stream.feed("[A] split\r\n[PW][2][3ms][INFO][A] next\n");
    assert(lines.size() == 2U && pigweed_log::parse(lines[0], record));
    assert(record.message == "split");
    assert(stream.feed(std::string(513, 'x')).empty());
    assert(stream.feed("[PW][3][4ms][INFO][A] suffix\n").empty());
    assert(stream.oversized() == 1U);
    assert(stream.feed("[PW][4][5ms][INFO][A] recovered\n").size() == 1U);
}
