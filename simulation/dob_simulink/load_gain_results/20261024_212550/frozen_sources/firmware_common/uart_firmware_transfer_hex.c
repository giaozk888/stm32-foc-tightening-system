#include "uart_firmware_transfer.h"
#include <string.h>
static int nibble(char c) {
    return c >= '0' && c <= '9' ? c - '0' : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}
size_t PW_UartFirmwareTransfer_Unhex(const char *text, uint8_t *out, size_t capacity) {
    if (!text || !out)
        return 0;
    const size_t n = strlen(text);
    if (!n || n % 2 || n / 2 > capacity)
        return 0;
    for (size_t i = 0; i < n / 2; ++i) {
        int a = nibble(text[2 * i]), b = nibble(text[2 * i + 1]);
        if (a < 0 || b < 0)
            return 0;
        out[i] = (uint8_t)((a << 4) | b);
    }
    return n / 2;
}
