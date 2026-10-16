#ifndef ESP_PING_H
#define ESP_PING_H

#include <stdint.h>
#include <string.h>

/* Pure parser shared by the UART ingress whitelist and ProtocolTask.
 * Only the ESP32 diagnostic reply is accepted; no arbitrary Protocol V2
 * command can enter through this path. */
static inline uint8_t EspPing_ParsePongPayload(const char *payload,
                                               uint16_t *request_id)
{
    const char *p = payload;
    uint32_t value = 0U;
    uint32_t digits = 0U;

    if ((p == NULL) || (*p < '1') || (*p > '9'))
    {
        return 0U;
    }
    while ((*p >= '0') && (*p <= '9'))
    {
        value = value * 10U + (uint32_t)(*p - '0');
        digits++;
        if ((digits > 5U) || (value > 65535U))
        {
            return 0U;
        }
        p++;
    }
    if (strcmp(p, " OK ESP32 PONG") != 0)
    {
        return 0U;
    }
    if (request_id != NULL)
    {
        *request_id = (uint16_t)value;
    }
    return 1U;
}

#endif /* ESP_PING_H */
