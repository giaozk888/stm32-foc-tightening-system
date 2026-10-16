#include "network_v1.h"
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uint32_t net_crc32(const char *data, size_t length)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < length; ++i) {
        crc ^= (uint8_t)data[i];
        for (unsigned j = 0; j < 8; ++j)
            crc = (crc >> 1) ^ ((crc & 1U) ? UINT32_C(0xedb88320) : 0U);
    }
    return ~crc;
}

bool net_sample_valid(const net_sample_t *s)
{
    return s != NULL && s->cycle <= 5U && s->stage <= 11U &&
           s->outcome <= 6U && s->flags <= 127U && s->vbus_mv <= 100000U &&
           (s->vbus_quality & ~31U) == 0U && s->kind <= NET_KIND_RESULT &&
           (s->kind != NET_KIND_RESULT ||
            (s->run != 0U && s->cycle != 0U && s->outcome != 0U));
}

size_t net_sample_format(const net_sample_t *s, char *out, size_t capacity)
{
    if (!net_sample_valid(s) || out == NULL || capacity == 0) return 0;
    int n = snprintf(out, capacity,
        "NET1 %" PRIu32 " %" PRIu32 " %" PRIu32 " %u %u %u %u %u "
        "%" PRId32 " %" PRId32 " %" PRId32 " %" PRIu32 " %u "
        "%" PRId32 " %" PRId32 " %u",
        s->seq, s->uptime_ms, s->run, s->cycle, s->stage, s->outcome,
        s->flags, s->fault, s->position_cdeg, s->speed_drpm, s->iq_ma,
        s->vbus_mv, s->vbus_quality, s->contact_cdeg, s->post_cdeg, s->kind);
    if (n < 0 || (size_t)n + 10U > capacity) return 0;
    uint32_t crc = net_crc32(out, (size_t)n);
    int tail = snprintf(out + n, capacity - (size_t)n, " %08" PRIX32, crc);
    return tail == 9 ? (size_t)n + 9U : 0;
}

bool net_sample_parse(const char *line, net_sample_t *out)
{
    if (line == NULL || out == NULL || strncmp(line, "NET1 ", 5) != 0 ||
        strlen(line) > 224U) return false;
    const char *crc_text = strrchr(line, ' ');
    if (crc_text == NULL || strlen(crc_text + 1) != 8U) return false;
    for (unsigned i = 1; i <= 8; ++i)
        if (!((crc_text[i] >= '0' && crc_text[i] <= '9') ||
              (crc_text[i] >= 'A' && crc_text[i] <= 'F'))) return false;
    char *end;
    errno = 0;
    unsigned long crc = strtoul(crc_text + 1, &end, 16);
    if (errno || *end || crc != net_crc32(line, (size_t)(crc_text - line)))
        return false;
    int64_t v[16];
    const char *p = line + 5;
    for (unsigned i = 0; i < 16; ++i) {
        if (!((*p >= '0' && *p <= '9') ||
              (*p == '-' && p[1] >= '0' && p[1] <= '9'))) return false;
        errno = 0;
        v[i] = strtoll(p, &end, 10);
        if (errno || *end != ' ') return false;
        if (i == 8 || i == 9 || i == 10 || i == 13 || i == 14) {
            if (v[i] < INT32_MIN || v[i] > INT32_MAX) return false;
        } else if (v[i] < 0 || v[i] > UINT32_MAX) return false;
        p = end + 1;
    }
    if (p != crc_text + 1 || v[3] > 5 || v[4] > 11 || v[5] > 6 ||
        v[6] > 127 || v[7] > UINT16_MAX || v[12] > 31 || v[15] > 1)
        return false;
    net_sample_t s = {
        .seq = (uint32_t)v[0], .uptime_ms = (uint32_t)v[1], .run = (uint32_t)v[2],
        .cycle = (uint8_t)v[3], .stage = (uint8_t)v[4], .outcome = (uint8_t)v[5],
        .flags = (uint8_t)v[6], .fault = (uint16_t)v[7],
        .position_cdeg = (int32_t)v[8], .speed_drpm = (int32_t)v[9],
        .iq_ma = (int32_t)v[10], .vbus_mv = (uint32_t)v[11],
        .vbus_quality = (uint16_t)v[12], .contact_cdeg = (int32_t)v[13],
        .post_cdeg = (int32_t)v[14], .kind = (uint8_t)v[15]
    };
    if (!net_sample_valid(&s)) return false;
    *out = s;
    return true;
}
