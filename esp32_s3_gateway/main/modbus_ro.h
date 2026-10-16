#ifndef MODBUS_RO_H
#define MODBUS_RO_H
#include "network_v1.h"
#define MB_REGISTER_COUNT 40U
typedef struct {
    net_sample_t sample;
    uint32_t age_ms, uploaded, queued, dropped, upload_errors, rejected;
    bool available, wifi;
} mb_observation_t;
/* Complete MBAP ADU only; invalid framing returns zero (close connection).
   Unit 1, FC04 only. No downstream UART/RTU or actuator access. */
size_t mb_readonly_reply(const uint8_t *request, size_t length,
                        const mb_observation_t *state, uint8_t *reply,
                        size_t capacity);
#endif
