#include "can_fd_probe.h"
#include "can_wire_profile.h"
#include <array>
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cstring>

static void put32(unsigned char *p, uint32_t n) {
    for (unsigned i = 0; i < 4; ++i)
        p[i] = static_cast<unsigned char>(n >> (8U * i));
}

int main() {
    static_assert(CAN_WIRE_FD_ENABLED == 0, "Classic is the default");
    static_assert(CAN_WIRE_CLOCK_HZ / (CAN_WIRE_NOMINAL_PRESCALER *
                                       (1U + CAN_WIRE_NOMINAL_SEG1 + CAN_WIRE_NOMINAL_SEG2)) ==
                      500000U,
                  "Nominal timing");
    static_assert(CAN_WIRE_CLOCK_HZ / (CAN_WIRE_DATA_PRESCALER *
                                       (1U + CAN_WIRE_DATA_SEG1 + CAN_WIRE_DATA_SEG2)) ==
                      2000000U,
                  "Data timing");
    const unsigned char lengths[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64};
    for (unsigned i = 0; i < 16; ++i)
        assert(CanWire_DlcBytes(i) == lengths[i]);
    assert(CanWire_DlcBytes(16) == 0 && CanWire_DlcBytes(0xffffffffU) == 0);
    assert(CanWire_ModeMatches(0, 0) && CanWire_ModeMatches(1, 1));
    assert(!CanWire_ModeMatches(0, 1) && !CanWire_ModeMatches(1, 0));
    assert(CanWire_TxAllowed(CAN_FD_PROBE_REPLY_ID, 1));
    for (uint32_t id = 0; id <= 0x7ffU; ++id) {
        assert(CanWire_TxAllowed(id, 0));
        assert(CanWire_TxAllowed(id, 1) == (id == CAN_FD_PROBE_REPLY_ID));
    }
    assert(CanFdProbe_Crc32(reinterpret_cast<const unsigned char *>("123456789"), 9) ==
           0xcbf43926U);
    std::array<unsigned char, 64> data{};
    std::memcpy(data.data(), "CFD1", 4);
    put32(data.data() + 4, 0x12345678U);
    for (unsigned i = 8; i < 60; ++i)
        data[i] = static_cast<unsigned char>(i);
    put32(data.data() + 60, CanFdProbe_Crc32(data.data(), 60));
    assert(CanFdProbe_Validate(data.data(), data.size()));
    assert(!CanFdProbe_Validate(nullptr, 64));
    assert(!CanFdProbe_Validate(data.data(), 8));
    assert(!CanFdProbe_Validate(data.data(), 63));
    assert(!CanFdProbe_Validate(data.data(), 65));
    for (unsigned i = 0; i < 64; ++i) {
        data[i] ^= 1;
        assert(!CanFdProbe_Validate(data.data(), data.size()));
        data[i] ^= 1;
    }
    put32(data.data() + 4, 0);
    put32(data.data() + 60, CanFdProbe_Crc32(data.data(), 60));
    assert(!CanFdProbe_Validate(data.data(), data.size()));
}
