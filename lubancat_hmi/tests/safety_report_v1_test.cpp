#include "safety_report_v1.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main()
{
    safety_report_v1::Packet out;
    std::uint8_t frame[8] = {1, 3, 0x31, 0, 1, 1, 0xff, 0xff};
    assert(safety_report_v1::decode(0x184, false, false, false, 8, frame, out));
    assert(out.missing == 0x31U && out.sequence == 65535U);
    for (unsigned bit = 0; bit < 3; ++bit)
        assert(!safety_report_v1::decode(0x184, bit == 0, bit == 1, bit == 2, 8, frame, out));
    assert(!safety_report_v1::decode(0x183, false, false, false, 8, frame, out));
    assert(!safety_report_v1::decode(0x184, false, false, false, 7, frame, out));
    assert(!safety_report_v1::decode(0x184, false, false, false, 8, nullptr, out));
    frame[1] = 0;
    assert(!safety_report_v1::decode(0x184, false, false, false, 8, frame, out));
    frame[1] = 3; frame[2] = 1;
    assert(!safety_report_v1::decode(0x184, false, false, false, 8, frame, out));
    frame[2] = 0x31; frame[3] = 8;
    assert(!safety_report_v1::decode(0x184, false, false, false, 8, frame, out));
    frame[3] = 0;
    assert(safety_report_v1::decode(0x184, false, false, false, 8, frame, out));
    safety_report_v1::Tracker tracker;
    assert(!tracker.accept(out, -1));
    assert(tracker.accept(out, 100));
    assert(!tracker.accept(out, 200));
    assert(tracker.fresh(600) && !tracker.fresh(601));
    out.sequence = 0;
    assert(tracker.accept(out, 300));
    assert(!tracker.accept(out, 299));
    out.sequence = 100;
    assert(tracker.accept(out, 400));
    out.sequence = 99;
    assert(!tracker.accept(out, 450));
    out.sequence = 0;
    assert(tracker.accept(out, 901)); // Reboot baseline after expiration.
    safety_report_v1::RawPacket raw;
    safety_report_v1::RawTracker rawTracker;
    std::uint8_t values[8] = {0x58, 2, 0x59, 2, 0x5a, 2, 0, 0};
    assert(safety_report_v1::decodeRaw(0x185, false, false, false, 8, values, raw));
    assert(raw.raw[0] == 600 && raw.channel == 0);
    assert(rawTracker.accept(raw, 902));
    assert(!rawTracker.accept(raw, 903)); // Duplicate cannot refresh data.
    assert(!rawTracker.accept(raw, 901)); // Clock going backwards.
    assert(rawTracker.matching(0, tracker, 903));
    assert(!rawTracker.matching(1, tracker, 903));
    assert(!rawTracker.matching(0, tracker, 1402)); // Report expiration.
    out.sequence = 1;
    assert(tracker.accept(out, 950));
    assert(!rawTracker.matching(0, tracker, 951)); // Do not combine different groups.
    values[6] = 1;
    assert(safety_report_v1::decodeRaw(0x186, false, false, false, 8, values, raw));
    assert(rawTracker.accept(raw, 952));
    assert(rawTracker.matching(1, tracker, 953));
    assert(!safety_report_v1::decodeRaw(0x184, false, false, false, 8, values, raw));
    assert(!safety_report_v1::decodeRaw(0x185, true, false, false, 8, values, raw));
    assert(!safety_report_v1::decodeRaw(0x185, false, false, false, 7, values, raw));
    values[0] = 0xff; values[1] = 0xff;
    assert(!safety_report_v1::decodeRaw(0x185, false, false, false, 8, values, raw));
    for (unsigned i = 0; i < 6; ++i) values[i] = 0xff;
    assert(safety_report_v1::decodeRaw(0x185, false, false, false, 8, values, raw));
    assert(raw.raw[0] == UINT16_MAX);
    frame[1] = 1; frame[4] = 1; frame[5] = 1;
    assert(!safety_report_v1::decode(0x184, false, false, false, 8, frame, out));
    frame[4] |= SAMPLE_ACQUISITION; frame[5] |= SAMPLE_ACQUISITION;
    assert(safety_report_v1::decode(0x184, false, false, false, 8, frame, out));
}
