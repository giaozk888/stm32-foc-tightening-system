#ifndef ROUTER_UART_TX_H
#define ROUTER_UART_TX_H
#include "router.h"
#include "uart_async.h"

/* Runtime only. Small encoded frames stay in the fixed TX pool; medium frames
 * use the hybrid allocator. Generate directly into final DMA storage. */
static inline uint8_t RouterUartTx_Queue(const RouterPacket_t *packet, uint32_t timeout_ms) {
    if (packet == NULL || packet->length > ROUTER_MAX_PAYLOAD)
        return 0U;
    const size_t capacity = packet->length + 96U;
    UART_AsyncTxLease_t lease = {0};
    if (!UART_Async_Acquire(capacity, timeout_ms, &lease))
        return 0U;
    char *out = (char *)lease.data;
    out[0] = '\r';
    out[1] = '\n';
    size_t length = Router_EncodeAsciiFrame(packet, out + 2U, capacity - 2U);
    if (length == 0U || length + 4U >= capacity) {
        (void)UART_Async_Cancel(&lease);
        return 0U;
    }
    length += 2U;
    out[length++] = '\r';
    out[length++] = '\n';
    out[length] = '\0';
    if (UART_Async_Commit(&lease, length))
        return 1U;
    (void)UART_Async_Cancel(&lease);
    return 0U;
}
#endif
