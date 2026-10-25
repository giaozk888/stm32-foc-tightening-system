#ifndef CAN_FD_PROBE_H
#define CAN_FD_PROBE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Dedicated non-actuating echo, not an RPC/Flash/motor command. */
#define CAN_FD_PROBE_REQUEST_ID 0x702U
#define CAN_FD_PROBE_REPLY_ID 0x703U
#define CAN_FD_PROBE_BYTES 64U
#define CAN_FD_PROBE_LIFETIME_MS 500U
uint32_t CanFdProbe_Crc32(const uint8_t *data, size_t size);
int CanFdProbe_Validate(const uint8_t *data, size_t size);

#ifdef __cplusplus
}
#endif
#endif
