#ifndef UART_ASYNC_H
#define UART_ASYNC_H

#include "main.h"
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>
#include "uart_tx_pool.h"
#include "uart_tx_reference.h"
#include "pw_managed_buffer.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * FreeRTOS + DMA non-blocking UART TX backend.
 *
 * Current STM32G474 project mapping:
 *   UART      : LPUART1
 *   TX DMA    : DMA1 Channel 1
 *   DMAMUX req: DMA_REQUEST_LPUART1_TX
 *   IRQ prio  : 6
 *
 * IRQ priority 6 is intentionally below the configured
 * configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY = 5, so the DMA callback may
 * safely use xSemaphoreGiveFromISR().
 */
HAL_StatusTypeDef UART_Async_Init(UART_HandleTypeDef *huart);

/* Task-context lease API. FIFO is by successful commit publication, not by
 * acquire order. A preempted WRITING producer cannot block ready messages.
 * Fixed-pool publication uses lock-free 32-bit atomics. With hybrid allocation,
 * medium non-real-time payloads use pw_allocator and a task-level mutex.
 * Neither RTOS waits nor the entire hybrid path are globally lock-free.
 * Acquire/commit/cancel use a single-owner lease. Do not access after commit.
 * Outstanding leases must be cancelled by their owner on all failure paths. */
typedef struct {
    uint8_t *data;
    size_t capacity;
    UartTxLease pool;
    PW_BufferLease managed;
} UART_AsyncTxLease_t;
int UART_Async_Acquire(size_t capacity, uint32_t timeout_ms,
                       UART_AsyncTxLease_t *lease);
int UART_Async_Commit(UART_AsyncTxLease_t *lease, size_t length);
int UART_Async_Cancel(UART_AsyncTxLease_t *lease);
/* Shared-owner/static-reference APIs are declared in uart_tx_reference.h. */
size_t UART_Async_VPrintf(size_t capacity, uint32_t timeout_ms,
                          const char *format, va_list args);
size_t UART_Async_Printf(size_t capacity, uint32_t timeout_ms,
                         const char *format, ...);

typedef struct {
    uint32_t native_frames;
    uint32_t copy_frames;
    uint32_t copied_bytes;
    uint32_t completed_frames;
    uint32_t aborted_frames;
    uint32_t acquire_failures;
    uint32_t format_errors;
    uint32_t reserved_blocks;
    uint32_t queued_bytes;
    uint32_t shared_frames;
    uint32_t managed_frames;
    uint32_t managed_fallbacks;
} UART_AsyncDiagnostics_t;
void UART_Async_GetDiagnostics(UART_AsyncDiagnostics_t *out);

/* Legacy interfaces below COPY caller payload; use leases for zero-copy. */
size_t UART_Async_Write(const uint8_t *data, size_t len);
size_t UART_Async_WriteString(const char *str);

/*
 * Reliable enqueue for protocol/router traffic.
 *
 * Unlike UART_Async_Write(), this function may wait briefly for TX-pool
 * space. It returns len only after the complete message has
 * been queued, otherwise 0 after timeout_ms.
 *
 * Compatibility for already-built caller buffers with no transferable lifetime.
 * New protocol replies/IAP ACKs should use leases or Printf/VPrintf with a
 * bounded timeout and check acceptance; "reliable" does not mean peer ACK.
 */
size_t UART_Async_WriteReliable(const uint8_t *data,
                                size_t len,
                                uint32_t timeout_ms);

size_t UART_Async_GetQueuedBytes(void);
uint32_t UART_Async_GetDroppedBytes(void);
uint32_t UART_Async_GetDmaErrorCount(void);

typedef enum
{
    UART_ASYNC_SELFTEST_PASS = 0,
    UART_ASYNC_SELFTEST_START_FAIL,
    UART_ASYNC_SELFTEST_TIMEOUT
} UART_AsyncSelfTestResult_t;

typedef struct
{
    HAL_StatusTypeDef start_status;
    uint32_t uart_gstate_before;
    uint32_t uart_gstate_after;
    uint32_t dma_state_before;
    uint32_t dma_state_after;
    uint32_t dma_remaining_before;
    uint32_t dma_remaining_after;
    uint32_t dma_ccr;
    uint32_t uart_cr3;
    uint32_t dma_request;
} UART_AsyncSelfTestInfo_t;

/*
 * Diagnostic only.
 * Startup-only: requires an empty pool and no competing TX producer.
 * Starts one direct LPUART1 TX DMA transaction, bypassing the pool/TX task,
 * then waits up to ~100 ms while yielding with vTaskDelay().
 *
 * PASS:
 *   bytes transferred AND HAL completion path returned UART gState to READY.
 *
 * TIMEOUT + remaining == 0:
 *   DMA moved the bytes, but IRQ/callback completion path is broken.
 *
 * TIMEOUT + remaining unchanged:
 *   DMA request path is not running (DMAMUX/request/channel/config issue).
 */
UART_AsyncSelfTestResult_t
UART_Async_RunDirectDmaSelfTest(UART_AsyncSelfTestInfo_t *info);

#ifdef __cplusplus
}
#endif

#endif /* UART_ASYNC_H */
