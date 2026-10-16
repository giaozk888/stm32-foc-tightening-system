#include "modbus_ro.h"
#include <string.h>
static uint16_t be16(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }
static void put16(uint8_t *p, uint16_t n) { p[0] = (uint8_t)(n >> 8); p[1] = (uint8_t)n; }
static void put32(uint16_t *r, unsigned i, uint32_t n)
{ r[i] = (uint16_t)(n >> 16); r[i + 1] = (uint16_t)n; }

size_t mb_readonly_reply(const uint8_t *q, size_t n,
                        const mb_observation_t *s, uint8_t *r, size_t cap)
{
    if (!q || !s || !r || n < 8 || n > 260 || be16(q + 2) != 0 ||
        be16(q + 4) != n - 6 || q[6] != 1 || cap < 9) return 0;
    uint8_t ex = 0;
    uint16_t addr = 0, qty = 0;
    if (q[7] != 4) ex = 1; /* Illegal function, including every write function. */
    else if (n != 12) ex = 3;
    else {
        addr = be16(q + 8); qty = be16(q + 10);
        if (qty == 0 || qty > 125) ex = 3;
        else if (addr >= MB_REGISTER_COUNT || qty > MB_REGISTER_COUNT - addr) ex = 2;
        else if ((!s->available || s->age_ms > 3000U) && addr < 30U && addr + qty > 8U)
            ex = 4; /* Do not present stale device observations as live data. */
    }
    memcpy(r, q, 4); r[6] = 1;
    if (ex) { put16(r + 4, 3); r[7] = q[7] | 0x80U; r[8] = ex; return 9; }
    size_t out = 9U + 2U * qty;
    if (cap < out) return 0;
    uint16_t regs[MB_REGISTER_COUNT] = {0};
    regs[0] = 1; regs[1] = (uint16_t)((s->wifi ? 1U : 0U) |
                  (s->available && s->age_ms <= 3000U ? 2U : 0U));
    regs[2] = 0; /* Control availability is unconditionally locked. */
    regs[3] = s->available ? (uint16_t)(s->sample.vbus_quality |
                          (s->age_ms > 3000U ? NET_VBUS_STALE : 0U))
                         : NET_VBUS_UNQUALIFIED | NET_VBUS_UNAVAILABLE | NET_VBUS_STALE;
    put32(regs, 4, s->age_ms);
    put32(regs, 6, s->sample.seq); put32(regs, 8, s->sample.uptime_ms);
    put32(regs, 10, s->sample.run); regs[12] = s->sample.cycle;
    regs[13] = s->sample.stage; regs[14] = s->sample.outcome;
    regs[15] = s->sample.flags; regs[16] = s->sample.fault;
    put32(regs, 18, (uint32_t)s->sample.position_cdeg);
    put32(regs, 20, (uint32_t)s->sample.speed_drpm);
    put32(regs, 22, (uint32_t)s->sample.iq_ma); put32(regs, 24, s->sample.vbus_mv);
    put32(regs, 26, (uint32_t)s->sample.contact_cdeg);
    put32(regs, 28, (uint32_t)s->sample.post_cdeg);
    put32(regs, 30, s->uploaded); put32(regs, 32, s->queued);
    put32(regs, 34, s->dropped); put32(regs, 36, s->upload_errors);
    put32(regs, 38, s->rejected);
    put16(r + 4, (uint16_t)(3U + 2U * qty)); r[7] = 4; r[8] = (uint8_t)(2U * qty);
    for (unsigned i = 0; i < qty; ++i) put16(r + 9 + 2 * i, regs[addr + i]);
    return out;
}
