#ifndef UART_TX_POOL_H
#define UART_TX_POOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define UART_TX_POOL_BYTES 8192U
#define UART_TX_POOL_BLOCK_BYTES 256U
#define UART_TX_POOL_BLOCKS 32U

/* A lease has exactly one owner. Commit/cancel transfers or ends ownership.
 * Never retain/access data after either succeeds. No arbitrary stack pointers
 * are accepted. init and consumer functions require a quiescent/single owner. */
typedef struct {
    uint8_t *data;
    size_t capacity;
    uint32_t block;
    uint32_t token;
} UartTxLease;

typedef struct {
    const uint8_t *data;
    size_t length;
    uint32_t block;
    uint32_t token;
} UartTxMessage;

typedef void (*UartTxReleaseFn)(uint32_t context);

void UartTxPool_Init(void);
int UartTxPool_Acquire(size_t minimum_capacity, UartTxLease *out);
int UartTxPool_Commit(UartTxLease *lease, size_t length);
/* Trusted managed-buffer adapter only: data must remain immutable/alive until
 * release(context). Success transfers one owner reference; failure transfers
 * none. The descriptor reserves one 256B pool block, but payload is not copied.
 * The callback runs in the TX task after DMA completion/confirmed abort, never
 * in IRQ. It may perform bounded task-context deallocation under a mutex;
 * it must not re-enter/re-init the TX pool or wait for DMA. No stack pointers. */
int UartTxPool_CommitReference(UartTxLease *descriptor, const uint8_t *data,
                              size_t length, UartTxReleaseFn release, uint32_t context);
int UartTxPool_Cancel(UartTxLease *lease);
int UartTxPool_Begin(UartTxMessage *out);
int UartTxPool_Finish(UartTxMessage *message);
size_t UartTxPool_QueuedBytes(void);
size_t UartTxPool_ReservedBlocks(void);

#ifdef __cplusplus
}
#endif
#endif
