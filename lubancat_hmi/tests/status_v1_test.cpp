#include "status_v1.h"

#include <array>
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>

int main()
{
    std::array<std::uint8_t, 8> data{{1, 2, 0x05, 0x34, 0x12, 0xff, 0xff, 0}};
    status_v1::Packet packet;
    assert(status_v1::decode(0x180, false, false, false, 8, data.data(), packet));
    assert(packet.mode == 2 && packet.flags == 0x05);
    assert(packet.fault == 0x1234 && packet.sequence == 0xffff);
    assert(status_v1::sequenceForward(0, 0xffff));
    assert(!status_v1::sequenceForward(0xffff, 0xffff));
    assert(!status_v1::sequenceForward(0xfffe, 0xffff));
    assert(!status_v1::decode(0x181, false, false, false, 8, data.data(), packet));
    assert(!status_v1::decode(0x180, true, false, false, 8, data.data(), packet));
    assert(!status_v1::decode(0x180, false, true, false, 8, data.data(), packet));
    assert(!status_v1::decode(0x180, false, false, true, 8, data.data(), packet));
    assert(!status_v1::decode(0x180, false, false, false, 7, data.data(), packet));
    data[0] = 2;
    assert(!status_v1::decode(0x180, false, false, false, 8, data.data(), packet));
    data[0] = 1;
    data[7] = 1;
    assert(!status_v1::decode(0x180, false, false, false, 8, data.data(), packet));

    status_v1::Tracker tracker;
    assert(!tracker.seen() && !tracker.fresh(0));
    packet.sequence = 100;
    assert(tracker.accept(packet, 1000));
    assert(tracker.seen() && tracker.fresh(1500));
    assert(!tracker.fresh(1501));

    // Duplicates and backwards frames cannot refresh an otherwise live state.
    assert(!tracker.accept(packet, 1200));
    packet.sequence = 99;
    assert(!tracker.accept(packet, 1300));
    assert(tracker.packet().sequence == 100);
    assert(!tracker.fresh(1501));

    // After a timeout, a restarting controller may legitimately reset seq.
    packet.sequence = 0;
    assert(tracker.accept(packet, 1600));
    assert(tracker.fresh(1600) && tracker.packet().sequence == 0);
    packet.sequence = 1;
    assert(tracker.accept(packet, 1700));
    assert(tracker.fresh(2200) && !tracker.fresh(2201));

    // The wire sequence is uint16 and must also advance through wraparound.
    status_v1::Tracker wrapping;
    packet.sequence = 0xffff;
    assert(wrapping.accept(packet, 0));
    packet.sequence = 0;
    assert(wrapping.accept(packet, 100));
    assert(wrapping.packet().sequence == 0);
    return 0;
}
