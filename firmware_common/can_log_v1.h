#ifndef CAN_LOG_V1_H
#define CAN_LOG_V1_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define CAN_LOG_START_ID 0x680U
#define CAN_LOG_DATA_ID 0x681U
#define CAN_LOG_STATS_ID 0x682U
#define CAN_LOG_MAX_TEXT 192U
#define CAN_LOG_CHUNK_SIZE 5U
#define CAN_LOG_FLAG_SESSION_START 1U
typedef struct {
    uint16_t record_id;
    uint16_t crc;
    uint8_t length;
    uint8_t flags;
} CanLog_Start;
uint16_t CanLog_Crc16(const uint8_t *data, size_t size);
uint8_t CanLog_EncodeStart(uint16_t id, uint8_t flags, const uint8_t *text,
                           size_t length, uint8_t out[8]);
uint8_t CanLog_DecodeStart(const uint8_t data[8], CanLog_Start *out);
uint8_t CanLog_EncodeData(uint16_t id, uint8_t index, const uint8_t *text,
                          size_t length, uint8_t out[8]);
#ifdef __cplusplus
}
#endif
#endif
