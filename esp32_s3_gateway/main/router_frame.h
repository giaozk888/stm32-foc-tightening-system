#ifndef ROUTER_FRAME_H
#define ROUTER_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ROUTER_FRAME_MAX_PAYLOAD 224U
#define ROUTER_FRAME_MAX_LINE 320U

typedef struct {
    uint16_t src;
    uint16_t dst;
    uint8_t type;
    uint16_t seq;
    uint8_t ttl;
    uint16_t length;
    char payload[ROUTER_FRAME_MAX_PAYLOAD + 1U];
} router_frame_t;

bool router_frame_parse(const char *line, router_frame_t *frame);
size_t router_frame_format(const router_frame_t *frame, char *out,
                           size_t capacity);

#endif
