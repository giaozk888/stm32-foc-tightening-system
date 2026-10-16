#ifndef UART_RX_DMA_H
#define UART_RX_DMA_H

#include "main.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * LPUART1 RX DMA circular frontend.
 *
 * Data path:
 *   LPUART1 RX -> DMA1 Channel2 circular -> 1024-byte DMA buffer
 *              -> synchronous byte parser (no intermediate byte buffers)
 *
 * Recovery:
 * STM32 HAL may terminate DMA reception after blocking UART errors such as
 * ORE/FE/NE. HAL_UART_ErrorCallback() only records the fault and requests a
 * restart; the actual HAL abort/restart is performed from UART_RxDma_Poll()
 * in task context, never from the ISR callback.
 */
HAL_StatusTypeDef UART_RxDma_Init(UART_HandleTypeDef *huart);
void UART_RxDma_Poll(void);
/* Single RouterTask consumer. Callbacks must be synchronous, bounded and
 * nonblocking. Byte argument is a value, never a borrowed DMA pointer.
 * On loss/error the gap callback resets framing; discard to the next delimiter.
 * Firmware transport zero-copy removes DMA->software-ring->rx_buf copies;
 * parsing/Router packet storage still has its own data representation. */
typedef void (*UART_RxDma_ByteFn)(uint8_t byte, void *context);
typedef void (*UART_RxDma_GapFn)(void *context);
size_t UART_RxDma_Drain(UART_RxDma_ByteFn byte_fn, UART_RxDma_GapFn gap_fn,
                        void *context, size_t budget);
uint32_t UART_RxDma_GetGapCount(void);
uint32_t UART_RxDma_GetAmbiguousCount(void);

/* Copying compatibility API, not used by the runtime RouterTask. */
size_t UART_RxDma_Read(uint8_t *dst, size_t max_len);

uint8_t UART_RxDma_IsReady(void);
size_t UART_RxDma_GetQueuedBytes(void);
uint32_t UART_RxDma_GetTotalBytes(void);
uint32_t UART_RxDma_GetDroppedBytes(void);

uint32_t UART_RxDma_GetErrorCount(void);
uint32_t UART_RxDma_GetLastError(void);
uint32_t UART_RxDma_GetRestartCount(void);
uint32_t UART_RxDma_GetRestartFailureCount(void);
uint32_t UART_RxDma_GetDmaState(void);
uint32_t UART_RxDma_GetDmaRemaining(void);
uint32_t UART_RxDma_GetUartRxState(void);
uint32_t UART_RxDma_GetUartCr3(void);

/* GDB-visible live diagnostics. */
extern volatile uint32_t g_uart_rx_dma_error_count;
extern volatile uint32_t g_uart_rx_dma_last_error;
extern volatile uint32_t g_uart_rx_dma_restart_count;
extern volatile uint32_t g_uart_rx_dma_restart_failure_count;

#ifdef __cplusplus
}
#endif

#endif /* UART_RX_DMA_H */
