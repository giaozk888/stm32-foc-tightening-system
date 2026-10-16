#include "router_transfer_wire.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../can_rpc_host/test_assert.h"
int main(void) {
    assert(rn_transfer_crc32((const uint8_t *)"123456789", 9) == 0xCBF43926U);
    uint8_t data[1024];
    for (unsigned i = 0; i < sizeof(data); ++i)
        data[i] = (uint8_t)i;
    char text[225];
    rn_transfer_receiver_t r = {0};
    rn_transfer_view_t view;
    const unsigned count = 12;
    for (unsigned n = count; n-- > 0;) {
        assert(rn_transfer_format(1, data, sizeof(data), n * 88U, text, sizeof(text)));
        assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 3, &view) ==
               (n == 0 ? RN_TRANSFER_COMPLETE : RN_TRANSFER_PENDING));
        if (n != 0)
            assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 3, &view) == RN_TRANSFER_PENDING);
    }
    assert(view.size == 1024 && !memcmp(data, view.data, 1024));
    rn_transfer_release(&r, view.slot);
    assert(rn_transfer_format(2, data, 100, 0, text, sizeof(text)));
    assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, UINT32_MAX - 100U, &view) == RN_TRANSFER_PENDING);
    rn_transfer_expire(&r, 1900);
    assert(r.expired == 1);
    assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 0, &view) == RN_TRANSFER_PENDING);
    text[33] = text[33] == '0' ? '1' : '0';
    assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 0, &view) == RN_TRANSFER_REJECTED);
    assert(r.corrupt == 1);
    assert(rn_transfer_format(3, data, 100, 0, text, sizeof(text)));
    assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 0, &view) == RN_TRANSFER_PENDING);
    assert(rn_transfer_feed(&r, 4, 1, 1, 3, text, 0, &view) == RN_TRANSFER_REJECTED);
    assert(!rn_transfer_allowed(4, 65535, text));
    assert(!rn_transfer_allowed(4, 4, text));
    assert(rn_transfer_format(4, data, 100, 0, text, sizeof(text)));
    text[24] = text[24] == '0' ? '1' : '0';
    assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 0, &view) == RN_TRANSFER_PENDING);
    assert(rn_transfer_format(4, data, 100, 88, text, sizeof(text)));
    text[24] = text[24] == '0' ? '1' : '0';
    assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 0, &view) == RN_TRANSFER_REJECTED);
    assert(r.corrupt == 2);
    for (unsigned id = 5; id < 7; ++id) {
        assert(rn_transfer_format(id, data, 100, 0, text, sizeof(text)));
        assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 0, &view) == RN_TRANSFER_PENDING);
    }
    assert(rn_transfer_format(7, data, 100, 0, text, sizeof(text)));
    assert(rn_transfer_feed(&r, 4, 1, 1, 2, text, 0, &view) == RN_TRANSFER_REJECTED);
    rn_transfer_expire(&r, 2000);
    assert(r.expired == 3);
    assert(!rn_transfer_format(1, data, 1025, 0, text, sizeof(text)));
    assert(!rn_transfer_format(1, data, 100, 1, text, sizeof(text)));
    puts("TRANSFER WIRE PASS: 1024 bytes, reverse/duplicate, CRC, conflict, capacity, epoch, "
         "wrap/timeout");
}
