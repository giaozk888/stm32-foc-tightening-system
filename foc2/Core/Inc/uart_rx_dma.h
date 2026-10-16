#ifndef UART_RX_DMA_H
#define UART_RX_DMA_H

#include "main.h"
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * UART RX Layer 1B
 *
 *   LPUART1 RX
 *      -> DMA1 Channel2, circular mode
 *      -> 512-byte DMA buffer
 *      -> software RingBuffer
 *      -> ProtocolTask
 *
 * ProtocolTask polls the DMA producer position every 5 ms.
 * This first version intentionally does not need DMA1_Channel2_IRQHandler.
 */
HAL_StatusTypeDef UART_RxDma_Init(UART_HandleTypeDef *huart);
void UART_RxDma_Poll(void);
size_t UART_RxDma_Read(uint8_t *dst, size_t max_len);

uint8_t UART_RxDma_IsReady(void);
size_t UART_RxDma_GetQueuedBytes(void);
uint32_t UART_RxDma_GetTotalBytes(void);
uint32_t UART_RxDma_GetDroppedBytes(void);

#ifdef __cplusplus
}
#endif

#endif /* UART_RX_DMA_H */
