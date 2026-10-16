#include "can_log_v1.h"
#include <string.h>
uint16_t CanLog_Crc16(const uint8_t *data, size_t size)
{
    uint16_t crc = 0xffffU;
    for (size_t i = 0; i < size; ++i) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (uint16_t)((crc & 0x8000U) ? ((uint32_t)crc << 1) ^ 0x1021U : (uint32_t)crc << 1);
    }
    return crc;
}
uint8_t CanLog_EncodeStart(uint16_t id, uint8_t flags, const uint8_t *text,
                           size_t length, uint8_t out[8])
{
    if (!text || !out || !length || length > CAN_LOG_MAX_TEXT ||
        (flags & ~CAN_LOG_FLAG_SESSION_START)) return 0U;
    uint16_t crc = CanLog_Crc16(text, length);
    out[0] = 1U; out[1] = flags;
    out[2] = (uint8_t)id; out[3] = (uint8_t)(id >> 8);
    out[4] = (uint8_t)length;
    out[5] = (uint8_t)crc; out[6] = (uint8_t)(crc >> 8); out[7] = 0U;
    return 1U;
}
uint8_t CanLog_DecodeStart(const uint8_t data[8], CanLog_Start *out)
{
    if (!data || !out || data[0] != 1U || data[7] != 0U ||
        (data[1] & ~CAN_LOG_FLAG_SESSION_START) || !data[4] ||
        data[4] > CAN_LOG_MAX_TEXT) return 0U;
    out->record_id = (uint16_t)(data[2] | ((uint16_t)data[3] << 8));
    out->length = data[4]; out->flags = data[1];
    out->crc = (uint16_t)(data[5] | ((uint16_t)data[6] << 8));
    return 1U;
}
uint8_t CanLog_EncodeData(uint16_t id, uint8_t index, const uint8_t *text,
                          size_t length, uint8_t out[8])
{
    size_t offset = (size_t)index * CAN_LOG_CHUNK_SIZE;
    if (!text || !out || !length || length > CAN_LOG_MAX_TEXT || offset >= length)
        return 0U;
    size_t count = length - offset;
    if (count > CAN_LOG_CHUNK_SIZE) count = CAN_LOG_CHUNK_SIZE;
    memset(out, 0, 8);
    out[0] = (uint8_t)id; out[1] = (uint8_t)(id >> 8); out[2] = index;
    memcpy(out + 3, text + offset, count);
    return 1U;
}
