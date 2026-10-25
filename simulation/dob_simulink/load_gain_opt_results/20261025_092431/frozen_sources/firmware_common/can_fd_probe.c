#include "can_fd_probe.h"

static uint32_t read32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8U) | ((uint32_t)p[2] << 16U) |
           ((uint32_t)p[3] << 24U);
}

uint32_t CanFdProbe_Crc32(const uint8_t *data, size_t size) {
    uint32_t crc = 0xffffffffU;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8U; ++bit)
            crc = (crc >> 1U) ^ ((crc & 1U) ? 0xedb88320U : 0U);
    }
    return crc ^ 0xffffffffU;
}

int CanFdProbe_Validate(const uint8_t *data, size_t size) {
    return data != NULL && size == CAN_FD_PROBE_BYTES && data[0] == 'C' && data[1] == 'F' &&
           data[2] == 'D' && data[3] == '1' && read32(data + 4U) != 0U &&
           read32(data + 60U) == CanFdProbe_Crc32(data, 60U);
}
