#include "router_transfer_wire.h"
#include <stdio.h>
#include <string.h>

uint32_t rn_transfer_crc32(const uint8_t *data, size_t size) {
    uint32_t crc = UINT32_MAX;
    if (!data && size)
        return 0;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}
static bool hex(const char *p, unsigned count, uint32_t *out) {
    uint32_t value = 0;
    for (unsigned i = 0; i < count; ++i) {
        unsigned digit;
        if (p[i] >= '0' && p[i] <= '9')
            digit = (unsigned)(p[i] - '0');
        else if (p[i] >= 'A' && p[i] <= 'F')
            digit = (unsigned)(p[i] - 'A') + 10U;
        else
            return false;
        value = (value << 4) | digit;
    }
    *out = value;
    return true;
}
bool rn_transfer_parse(const char *text, rn_transfer_fragment_t *out) {
    if (!text || !out)
        return false;
    size_t length = 0;
    while (length <= 209U && text[length])
        ++length;
    if (length < 35U || length > 209U || (length - 33U) % 2U || strncmp(text, "XFER ", 5) ||
        text[13] != ' ' || text[18] != ' ' || text[23] != ' ' || text[32] != ' ')
        return false;
    uint32_t id, offset, total, crc;
    if (!hex(text + 5, 8, &id) || !id || !hex(text + 14, 4, &offset) ||
        !hex(text + 19, 4, &total) || !hex(text + 24, 8, &crc) || !total ||
        total > RN_TRANSFER_MAX_PACKET || offset >= total || offset % RN_TRANSFER_FRAGMENT)
        return false;
    const size_t size = (length - 33U) / 2U;
    const size_t remaining = total - offset;
    if (size != (remaining < RN_TRANSFER_FRAGMENT ? remaining : RN_TRANSFER_FRAGMENT))
        return false;
    *out = (rn_transfer_fragment_t){.id = id,
                                    .crc = crc,
                                    .offset = (uint16_t)offset,
                                    .total = (uint16_t)total,
                                    .size = (uint16_t)size};
    for (size_t i = 0; i < size; ++i) {
        uint32_t value;
        if (!hex(text + 33U + 2U * i, 2, &value))
            return false;
        out->data[i] = (uint8_t)value;
    }
    return true;
}
bool rn_transfer_allowed(uint16_t src, uint16_t dst, const char *text) {
    rn_transfer_fragment_t fragment;
    return src && src != UINT16_MAX && dst && dst != UINT16_MAX && src != dst &&
           rn_transfer_parse(text, &fragment);
}
size_t rn_transfer_format(uint32_t id, const uint8_t *packet, size_t total, size_t offset,
                          char *out, size_t capacity) {
    if (!id || !packet || !out || !total || total > RN_TRANSFER_MAX_PACKET || offset >= total ||
        offset % RN_TRANSFER_FRAGMENT)
        return 0;
    const size_t size =
        total - offset < RN_TRANSFER_FRAGMENT ? total - offset : RN_TRANSFER_FRAGMENT;
    if (capacity < 34U + 2U * size)
        return 0;
    int count =
        snprintf(out, capacity, "XFER %08lX %04X %04X %08lX ", (unsigned long)id, (unsigned)offset,
                 (unsigned)total, (unsigned long)rn_transfer_crc32(packet, total));
    if (count != 33)
        return 0;
    static const char digits[] = "0123456789ABCDEF";
    for (size_t i = 0; i < size; ++i) {
        out[33U + 2U * i] = digits[packet[offset + i] >> 4];
        out[34U + 2U * i] = digits[packet[offset + i] & 15U];
    }
    out[33U + 2U * size] = '\0';
    return 33U + 2U * size;
}
void rn_transfer_expire(rn_transfer_receiver_t *r, uint32_t now) {
    if (!r)
        return;
    for (unsigned i = 0; i < RN_TRANSFER_SLOTS; ++i)
        if (r->slots[i].used && !r->slots[i].held &&
            (uint32_t)(now - r->slots[i].started) >= RN_TRANSFER_TIMEOUT_MS) {
            r->slots[i].used = false;
            ++r->expired;
        }
}
void rn_transfer_release(rn_transfer_receiver_t *r, unsigned slot) {
    if (r && slot < RN_TRANSFER_SLOTS) {
        r->slots[slot].used = false;
        r->slots[slot].held = false;
    }
}
rn_transfer_result_t rn_transfer_feed(rn_transfer_receiver_t *r, uint16_t src, uint16_t dst,
                                      uint8_t port, uint32_t epoch, const char *text, uint32_t now,
                                      rn_transfer_view_t *view) {
    rn_transfer_fragment_t f;
    if (!r || !view)
        return RN_TRANSFER_REJECTED;
    *view = (rn_transfer_view_t){0};
    if (!rn_transfer_allowed(src, dst, text) || !rn_transfer_parse(text, &f)) {
        ++r->rejected;
        return RN_TRANSFER_REJECTED;
    }
    rn_transfer_expire(r, now);
    unsigned index = RN_TRANSFER_SLOTS;
    for (unsigned i = 0; i < RN_TRANSFER_SLOTS; ++i)
        if (r->slots[i].used && r->slots[i].src == src && r->slots[i].dst == dst &&
            r->slots[i].port == port && r->slots[i].id == f.id) {
            index = i;
            break;
        }
    if (index == RN_TRANSFER_SLOTS)
        for (unsigned i = 0; i < RN_TRANSFER_SLOTS; ++i)
            if (!r->slots[i].used) {
                index = i;
                break;
            }
    if (index == RN_TRANSFER_SLOTS) {
        ++r->rejected;
        return RN_TRANSFER_REJECTED;
    }
    rn_transfer_slot_t *s = &r->slots[index];
    if (!s->used) {
        s->used = true;
        s->held = false;
        s->src = src;
        s->dst = dst;
        s->port = port;
        s->epoch = epoch;
        s->id = f.id;
        s->crc = f.crc;
        s->total = f.total;
        s->bitmap = 0;
        s->started = now;
    } else if (s->held || s->epoch != epoch || s->crc != f.crc || s->total != f.total) {
        if (!s->held)
            s->used = false;
        ++r->rejected;
        return RN_TRANSFER_REJECTED;
    }
    const uint16_t bit = (uint16_t)(1U << (f.offset / RN_TRANSFER_FRAGMENT));
    if (s->bitmap & bit) {
        if (memcmp(s->data + f.offset, f.data, f.size)) {
            s->used = false;
            ++r->corrupt;
            return RN_TRANSFER_REJECTED;
        }
    } else {
        memcpy(s->data + f.offset, f.data, f.size);
        s->bitmap |= bit;
    }
    const unsigned pieces = (s->total + RN_TRANSFER_FRAGMENT - 1U) / RN_TRANSFER_FRAGMENT;
    if (s->bitmap != (uint16_t)((1U << pieces) - 1U))
        return RN_TRANSFER_PENDING;
    if (rn_transfer_crc32(s->data, s->total) != s->crc) {
        s->used = false;
        ++r->corrupt;
        return RN_TRANSFER_REJECTED;
    }
    s->held = true;
    ++r->completed;
    *view = (rn_transfer_view_t){.data = s->data, .size = s->total, .slot = index};
    return RN_TRANSFER_COMPLETE;
}
