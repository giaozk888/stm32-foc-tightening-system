#ifndef MOCK_STM32_HAL_H
#define MOCK_STM32_HAL_H
#include <stdint.h>
uint32_t HAL_GetTick(void);
typedef enum { HAL_OK = 0, HAL_ERROR = 1, HAL_BUSY = 2 } HAL_StatusTypeDef;
typedef struct { uint32_t CCR, CNDTR; } DMA_Channel_TypeDef;
typedef struct { uint32_t CR3; } USART_TypeDef;
typedef struct { int unused; } TIM_HandleTypeDef;
typedef struct {
    DMA_Channel_TypeDef *Instance;
    struct { uint32_t Request, Direction, PeriphInc, MemInc;
        uint32_t PeriphDataAlignment, MemDataAlignment, Mode, Priority; } Init;
    uint32_t State;
} DMA_HandleTypeDef;
typedef struct {
    USART_TypeDef *Instance;
    DMA_HandleTypeDef *hdmatx, *hdmarx;
    uint32_t gState, RxState, ErrorCode;
} UART_HandleTypeDef;
extern DMA_Channel_TypeDef mock_dma1, mock_dma2;
extern USART_TypeDef mock_uart;
extern uint32_t mock_rx_flags, mock_ipsr;
#define DMA1_Channel1 (&mock_dma1)
#define DMA1_Channel2 (&mock_dma2)
#define LPUART1 (&mock_uart)
#define DMA_CCR_EN 1U
#define DMA_FLAG_HT2 1U
#define DMA_FLAG_TC2 2U
#define DMA_REQUEST_LPUART1_TX 1U
#define DMA_REQUEST_LPUART1_RX 2U
#define DMA_MEMORY_TO_PERIPH 1U
#define DMA_PERIPH_TO_MEMORY 2U
#define DMA_PINC_DISABLE 0U
#define DMA_MINC_ENABLE 1U
#define DMA_PDATAALIGN_BYTE 0U
#define DMA_MDATAALIGN_BYTE 0U
#define DMA_NORMAL 0U
#define DMA_CIRCULAR 1U
#define DMA_PRIORITY_LOW 0U
#define DMA1_Channel1_IRQn 1
#define DMA1_Channel2_IRQn 2
#define HAL_UART_STATE_READY 0U
#define __HAL_RCC_DMAMUX1_CLK_ENABLE() ((void)0)
#define __HAL_RCC_DMA1_CLK_ENABLE() ((void)0)
#define __HAL_LINKDMA(u, field, d) ((u)->field = &(d))
#define __HAL_DMA_GET_COUNTER(d) ((d)->Instance->CNDTR)
#define __HAL_DMA_GET_FLAG(d, f) ((void)(d), mock_rx_flags & (f))
#define __get_IPSR() (mock_ipsr)
void mock_barrier(void);
#define __DMB() mock_barrier()
HAL_StatusTypeDef HAL_DMA_Init(DMA_HandleTypeDef *dma);
uint32_t HAL_DMA_GetState(DMA_HandleTypeDef *dma);
void HAL_DMA_IRQHandler(DMA_HandleTypeDef *dma);
void HAL_NVIC_SetPriority(int irq, uint32_t priority, uint32_t subpriority);
void HAL_NVIC_EnableIRQ(int irq);
void HAL_NVIC_DisableIRQ(int irq);
HAL_StatusTypeDef HAL_UART_Transmit_DMA(UART_HandleTypeDef *uart, uint8_t *data, uint16_t length);
HAL_StatusTypeDef HAL_UART_AbortTransmit(UART_HandleTypeDef *uart);
HAL_StatusTypeDef HAL_UART_Receive_DMA(UART_HandleTypeDef *uart, uint8_t *data, uint16_t length);
HAL_StatusTypeDef HAL_UART_AbortReceive(UART_HandleTypeDef *uart);
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *uart);
void HAL_UART_RxHalfCpltCallback(UART_HandleTypeDef *uart);
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *uart);
void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart);
void DMA1_Channel2_IRQHandler(void);
#endif
