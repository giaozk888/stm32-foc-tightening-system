#include "router_frame.h"

#include <stdio.h>
#include <string.h>

static bool parse_decimal(const char **cursor, uint32_t maximum,
                          uint32_t *value)
{
    const char *p = *cursor;
    uint32_t parsed = 0U;
    bool any = false;

    while (*p == ' ' || *p == '\t') {
        ++p;
    }
    while (*p >= '0' && *p <= '9') {
        const uint32_t digit = (uint32_t)(*p - '0');
        if (parsed > (maximum - digit) / 10U) {
            return false;
        }
        parsed = parsed * 10U + digit;
        any = true;
        ++p;
    }
    if (!any || (*p != ' ' && *p != '\t')) {
        return false;
    }
    *cursor = p;
    *value = parsed;
    return true;
}

bool router_frame_parse(const char *line, router_frame_t *frame)
{
    uint32_t src, dst, type, seq, ttl, length;
    const char *p;
    size_t actual;

    if (line == NULL || frame == NULL || strncmp(line, "@R1 ", 4U) != 0) {
        return false;
    }
    p = line + 4U;
    if (!parse_decimal(&p, UINT16_MAX, &src) ||
        !parse_decimal(&p, UINT16_MAX, &dst) ||
        !parse_decimal(&p, UINT8_MAX, &type) ||
        !parse_decimal(&p, UINT16_MAX, &seq) ||
        !parse_decimal(&p, UINT8_MAX, &ttl) ||
        !parse_decimal(&p, ROUTER_FRAME_MAX_PAYLOAD, &length)) {
        return false;
    }
    while (*p == ' ' || *p == '\t') {
        ++p;
    }
    actual = strlen(p);
    if (ttl == 0U || actual != length || actual > ROUTER_FRAME_MAX_PAYLOAD) {
        return false;
    }
    memset(frame, 0, sizeof(*frame));
    frame->src = (uint16_t)src;
    frame->dst = (uint16_t)dst;
    frame->type = (uint8_t)type;
    frame->seq = (uint16_t)seq;
    frame->ttl = (uint8_t)ttl;
    frame->length = (uint16_t)length;
    memcpy(frame->payload, p, actual + 1U);
    return true;
}

size_t router_frame_format(const router_frame_t *frame, char *out,
                           size_t capacity)
{
    int written;
    size_t actual;

    if (frame == NULL || out == NULL || capacity == 0U ||
        frame->ttl == 0U || frame->length > ROUTER_FRAME_MAX_PAYLOAD) {
        return 0U;
    }
    actual = strnlen(frame->payload, ROUTER_FRAME_MAX_PAYLOAD + 1U);
    if (actual != frame->length) {
        return 0U;
    }
    written = snprintf(out, capacity, "@R1 %u %u %u %u %u %u %s",
                       (unsigned)frame->src, (unsigned)frame->dst,
                       (unsigned)frame->type, (unsigned)frame->seq,
                       (unsigned)frame->ttl, (unsigned)frame->length,
                       frame->payload);
    if (written < 0 || (size_t)written >= capacity) {
        out[0] = '\0';
        return 0U;
    }
    return (size_t)written;
}
