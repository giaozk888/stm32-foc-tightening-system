#ifndef PROTOCOL_TX_BUFFER_H
#define PROTOCOL_TX_BUFFER_H

#include "uart_async.h"
#include <string.h>

/* A bounded builder for replies whose caller must inspect formatted length.
 * One owner; initialize empty, build synchronously, then commit or cancel.
 * Never retain/use data after commit. This is not an arbitrary stack reference. */
typedef struct {
    UART_AsyncTxLease_t lease;
    char *data;
    size_t capacity;
    uint8_t native;
} ProtocolTxBuffer;

static inline int ProtocolTxBuffer_Begin(ProtocolTxBuffer *out, uint8_t native, char *fallback,
                                         size_t capacity, uint32_t timeout_ms) {
    if (out == NULL || capacity == 0U)
        return 0;
    memset(out, 0, sizeof(*out));
    if (native != 0U) {
        if (!UART_Async_Acquire(capacity, timeout_ms, &out->lease))
            return 0;
        out->data = (char *)out->lease.data;
        out->native = 1U;
    } else {
        if (fallback == NULL)
            return 0;
        out->data = fallback;
    }
    out->capacity = capacity;
    return 1;
}

static inline void ProtocolTxBuffer_Cancel(ProtocolTxBuffer *buffer) {
    if (buffer == NULL)
        return;
    if (buffer->native != 0U)
        (void)UART_Async_Cancel(&buffer->lease);
    memset(buffer, 0, sizeof(*buffer));
}

static inline uint8_t ProtocolTxBuffer_Commit(ProtocolTxBuffer *buffer, int length,
                                              uint8_t (*fallback_send)(const char *)) {
    uint8_t accepted = 0U;
    if (buffer == NULL)
        return 0U;
    if (buffer->data != NULL && length > 0 && (size_t)length < buffer->capacity) {
        if (buffer->native != 0U) {
            accepted = UART_Async_Commit(&buffer->lease, (size_t)length) != 0;
        } else if (fallback_send != NULL) {
            /* As with the format dispatcher: synchronous consume/copy only. */
            accepted = fallback_send(buffer->data);
        }
    }
    /* A successful native commit already invalidates the lease. Cancel only
     * on failure; no releasing a buffer now owned by the TX task/DMA. */
    if (buffer->native != 0U && accepted == 0U)
        (void)UART_Async_Cancel(&buffer->lease);
    memset(buffer, 0, sizeof(*buffer));
    return accepted;
}

#endif /* PROTOCOL_TX_BUFFER_H */
