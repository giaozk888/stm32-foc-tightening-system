#ifndef UART_ASYNC_H
#define UART_ASYNC_H

#include "main.h"
#include <stddef.h>
#include <stdint.h>

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

uint8_t UART_Async_IsReady(void);

/*
 * All-or-nothing enqueue.
 * Returns len on success, 0 if there is not enough ring space or if another
 * producer currently owns the short write mutex.
 *
 * It never waits for bytes to leave the UART.
 */
size_t UART_Async_Write(const uint8_t *data, size_t len);
size_t UART_Async_WriteString(const char *str);

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
 * Starts one direct LPUART1 TX DMA transaction, bypassing the ring/TX task,
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
