#ifndef PROTOCOL_TX_FORMAT_H
#define PROTOCOL_TX_FORMAT_H

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

/* Task-context formatting dispatch. Native UART generates directly in a DMA
 * lease. Boot/routed output consumes the bounded fallback synchronously;
 * it must never retain a pointer to that caller-owned array. No heap needed. */
typedef size_t (*ProtocolTxNativeFormatFn)(size_t capacity, uint32_t timeout_ms, const char *format,
                                           va_list args);
typedef uint8_t (*ProtocolTxTextSendFn)(const char *text);

static inline uint8_t ProtocolTx_VFormat(uint8_t native_uart,
                                         ProtocolTxNativeFormatFn native_format,
                                         ProtocolTxTextSendFn fallback_send, char *fallback,
                                         size_t capacity, uint32_t timeout_ms, const char *format,
                                         va_list args) {
    int length;
    if (format == NULL || capacity == 0U)
        return 0U;
    if (native_uart != 0U) {
        /* Do not fall back to blocking UART/copying after a native failure. */
        return native_format != NULL && native_format(capacity, timeout_ms, format, args) != 0U;
    }
    if (fallback == NULL || fallback_send == NULL)
        return 0U;
    length = vsnprintf(fallback, capacity, format, args);
    /* Never publish a partial protocol line, including boot/router fallback. */
    if (length <= 0 || (size_t)length >= capacity)
        return 0U;
    return fallback_send(fallback);
}

#endif /* PROTOCOL_TX_FORMAT_H */
