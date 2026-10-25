#ifndef ROUTER_NETWORK_H
#define ROUTER_NETWORK_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* R1 remains wire compatible. Type 7 is a separate, numeric-only diagnostic
 * namespace; it MUST NOT be passed to the motor/Flash console parser. */
#define RN_DIAGNOSTIC_TYPE 7U
#define RN_MAX_LINE 320U
#define RN_MAX_PAYLOAD 224U
typedef struct {
    uint16_t src, dst, seq;
    uint8_t type, ttl;
    uint16_t length;
    char payload[RN_MAX_PAYLOAD + 1U];
} rn_frame_t;
typedef enum { RN_INVALID, RN_PING, RN_PONG, RN_STATUS, RN_INFO } rn_kind_t;
typedef struct {
    rn_kind_t kind;
    uint16_t nonce, node;
    uint32_t rx, tx, no_route, duplicate;
} rn_message_t;
typedef struct {
    char bytes[RN_MAX_LINE + 1U];
    size_t used;
    bool dropping;
    uint32_t rejected;
} rn_stream_t;
typedef void (*rn_line_fn)(void *context, const char *line);
bool rn_parse(const char *line, rn_frame_t *out);
size_t rn_format(const rn_frame_t *frame, char *out, size_t capacity);
bool rn_message_parse(const char *payload, rn_message_t *out);
bool rn_allowed(uint16_t src, uint16_t dst, uint8_t type, uint8_t ttl,
                const char *payload);
bool rn_line_allowed(const char *line);
void rn_stream_feed(rn_stream_t *stream, const uint8_t *bytes, size_t count,
                    rn_line_fn callback, void *context);
#ifdef __cplusplus
}
#endif
#endif
