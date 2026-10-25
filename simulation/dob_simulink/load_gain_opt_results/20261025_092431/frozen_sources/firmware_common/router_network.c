#include "router_network.h"
#if defined(ROUTER_READ_ONLY_RPC)
#include "router_rpc_wire.h"
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
#include "router_transfer_wire.h"
#endif
#include <stdio.h>
#include <string.h>

static bool number(const char **cursor, uint32_t maximum, uint32_t *out)
{
    const char *p = *cursor;
    uint32_t value = 0;
    if (*p < '0' || *p > '9') return false;
    do {
        uint32_t digit = (uint32_t)(*p++ - '0');
        if (value > (maximum - digit) / 10U) return false;
        value = value * 10U + digit;
    } while (*p >= '0' && *p <= '9');
    if (*p != ' ' && *p != '\0') return false;
    *cursor = p; *out = value;
    return true;
}
static bool next_number(const char **p, uint32_t maximum, uint32_t *out)
{
    if (**p != ' ') return false;
    ++*p;
    return number(p, maximum, out);
}
bool rn_parse(const char *line, rn_frame_t *out)
{
    uint32_t src, dst, type, seq, ttl, length;
    if (!line || !out || strncmp(line, "@R1 ", 4U)) return false;
    size_t line_length = 0;
    while (line[line_length] && line_length <= RN_MAX_LINE) ++line_length;
    if (line_length > RN_MAX_LINE) return false;
    const char *p = line + 4;
    if (!number(&p, UINT16_MAX, &src) ||
        !next_number(&p, UINT16_MAX, &dst) ||
        !next_number(&p, UINT8_MAX, &type) ||
        !next_number(&p, UINT16_MAX, &seq) ||
        !next_number(&p, UINT8_MAX, &ttl) ||
        !next_number(&p, RN_MAX_PAYLOAD, &length) || *p++ != ' ') return false;
    size_t actual = strlen(p);
    if (!ttl || actual != length || actual > RN_MAX_PAYLOAD) return false;
    for (size_t i = 0; i < actual; ++i)
        if ((unsigned char)p[i] < 32U || (unsigned char)p[i] > 126U) return false;
    *out = (rn_frame_t){.src=(uint16_t)src, .dst=(uint16_t)dst,
        .type=(uint8_t)type, .seq=(uint16_t)seq, .ttl=(uint8_t)ttl,
        .length=(uint16_t)length};
    memcpy(out->payload, p, actual + 1U);
    return true;
}
size_t rn_format(const rn_frame_t *f, char *out, size_t capacity)
{
    if (!f || !out || !capacity || !f->ttl || f->length > RN_MAX_PAYLOAD ||
        memchr(f->payload, '\0', sizeof(f->payload)) != f->payload + f->length)
        return 0;
    for (size_t i = 0; i < f->length; ++i)
        if ((unsigned char)f->payload[i] < 32U || (unsigned char)f->payload[i] > 126U)
            return 0;
    int n = snprintf(out, capacity, "@R1 %u %u %u %u %u %u %s",
        (unsigned)f->src, (unsigned)f->dst, (unsigned)f->type,
        (unsigned)f->seq, (unsigned)f->ttl, (unsigned)f->length, f->payload);
    if (n < 0 || (size_t)n >= capacity) { out[0] = '\0'; return 0; }
    return (size_t)n;
}
bool rn_message_parse(const char *payload, rn_message_t *out)
{
    if (!payload || !out) return false;
    rn_message_t m = {0};
    const char *p;
    if (!strncmp(payload, "PING ", 5)) { m.kind = RN_PING; p = payload + 5; }
    else if (!strncmp(payload, "PONG ", 5)) { m.kind = RN_PONG; p = payload + 5; }
    else if (!strncmp(payload, "STATUS ", 7)) { m.kind = RN_STATUS; p = payload + 7; }
    else if (!strncmp(payload, "INFO ", 5)) { m.kind = RN_INFO; p = payload + 5; }
    else return false;
    uint32_t nonce, node;
    if (!number(&p, UINT16_MAX, &nonce) || !nonce) return false;
    m.nonce = (uint16_t)nonce;
    if (m.kind == RN_PONG || m.kind == RN_INFO) {
        if (!next_number(&p, 65534U, &node) || !node) return false;
        m.node = (uint16_t)node;
    }
    if (m.kind == RN_INFO &&
        (!next_number(&p, UINT32_MAX, &m.rx) ||
         !next_number(&p, UINT32_MAX, &m.tx) ||
         !next_number(&p, UINT32_MAX, &m.no_route) ||
         !next_number(&p, UINT32_MAX, &m.duplicate))) return false;
    if (*p) return false;
    *out = m;
    return true;
}
bool rn_allowed(uint16_t src, uint16_t dst, uint8_t type, uint8_t ttl,
                const char *payload)
{
    if (!src || src == 65535U || !dst || !ttl || ttl > 8U || !payload) return false;
    if (type == 3U)
        return (!strcmp(payload, "HELLO") && dst == 65535U) ||
               (!strcmp(payload, "ANNOUNCE") && dst != 65535U);
#if defined(ROUTER_READ_ONLY_RPC)
    if (type == RN_RPC_TYPE) return rn_rpc_allowed(src,dst,payload);
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
    if (type == RN_TRANSFER_TYPE) return rn_transfer_allowed(src,dst,payload);
#endif
    rn_message_t m;
    return type == RN_DIAGNOSTIC_TYPE && dst != 65535U &&
        rn_message_parse(payload, &m) &&
        ((m.kind != RN_PONG && m.kind != RN_INFO) || m.node == src);
}
bool rn_line_allowed(const char *line)
{
    rn_frame_t f;
    return rn_parse(line, &f) && rn_allowed(f.src, f.dst, f.type, f.ttl, f.payload);
}
void rn_stream_feed(rn_stream_t *s, const uint8_t *bytes, size_t count,
                    rn_line_fn callback, void *context)
{
    if (!s || !bytes || !callback) return;
    for (size_t i = 0; i < count; ++i) {
        uint8_t c = bytes[i];
        if (c == '\r' || c == '\n') {
            if (!s->dropping && s->used) {
                s->bytes[s->used] = '\0'; callback(context, s->bytes);
            }
            s->used = 0; s->dropping = false;
        } else if (!s->dropping) {
            if (c < 32U || c > 126U || s->used >= RN_MAX_LINE) {
                s->dropping = true; s->used = 0; ++s->rejected;
            } else s->bytes[s->used++] = (char)c;
        }
    }
}
