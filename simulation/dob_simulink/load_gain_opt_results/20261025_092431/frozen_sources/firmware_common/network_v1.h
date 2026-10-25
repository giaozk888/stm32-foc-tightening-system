#ifndef NETWORK_V1_H
#define NETWORK_V1_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Observation only. No command, permission or calibrated torque fields. */
#define NET_FLAG_ENCODER 1U
#define NET_FLAG_IQ 2U
#define NET_FLAG_BUSY 4U
#define NET_FLAG_SAFE 8U
#define NET_FLAG_CONTACT 16U
#define NET_FLAG_SD 32U
#define NET_FLAG_FAULT 64U
#define NET_KIND_SAMPLE 0U
#define NET_KIND_RESULT 1U
#define NET_VBUS_UNQUALIFIED 1U
#define NET_VBUS_UNAVAILABLE 2U
#define NET_VBUS_STALE 16U

typedef struct {
    uint32_t seq, uptime_ms, run;
    uint8_t cycle, stage, outcome, flags;
    uint16_t fault;
    int32_t position_cdeg, speed_drpm, iq_ma;
    uint32_t vbus_mv;
    uint16_t vbus_quality;
    int32_t contact_cdeg, post_cdeg;
    uint8_t kind;
} net_sample_t;

bool net_sample_valid(const net_sample_t *s);
size_t net_sample_format(const net_sample_t *s, char *out, size_t capacity);
bool net_sample_parse(const char *line, net_sample_t *out);
uint32_t net_crc32(const char *data, size_t length);
#endif
