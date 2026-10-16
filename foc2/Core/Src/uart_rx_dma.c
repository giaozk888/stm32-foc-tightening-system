#include "uart_rx_dma.h"
#include "ring_buffer.h"

#include <string.h>

#define UART_RX_DMA_BUFFER_SIZE   512U
#define UART_RX_SW_RING_SIZE      512U

static UART_HandleTypeDef *s_uart = NULL;
static DMA_HandleTypeDef s_hdma_rx;

static uint8_t s_dma_buffer[UART_RX_DMA_BUFFER_SIZE];
static uint8_t s_ring_storage[UART_RX_SW_RING_SIZE];
static RingBuffer_t s_rx_ring;

static size_t s_dma_last_pos = 0U;
static volatile uint8_t s_ready = 0U;
static volatile uint32_t s_total_bytes = 0U;
static volatile uint32_t s_dropped_bytes = 0U;


static void UART_RxDma_PushChunk(const uint8_t *src, size_t len)
{
    size_t written;

    if ((src == NULL) || (len == 0U))
    {
        return;
    }

    s_total_bytes += (uint32_t)len;

    written = RingBuffer_Write(&s_rx_ring, src, len);

    if (written < len)
    {
        s_dropped_bytes += (uint32_t)(len - written);
    }
}


HAL_StatusTypeDef UART_RxDma_Init(UART_HandleTypeDef *huart)
{
    HAL_StatusTypeDef st;

    if (huart == NULL)
    {
        return HAL_ERROR;
    }

    s_ready = 0U;
    s_uart = huart;
    s_dma_last_pos = 0U;
    s_total_bytes = 0U;
    s_dropped_bytes = 0U;

    memset(&s_hdma_rx, 0, sizeof(s_hdma_rx));
    memset(s_dma_buffer, 0, sizeof(s_dma_buffer));
    memset(s_ring_storage, 0, sizeof(s_ring_storage));

    RingBuffer_Init(&s_rx_ring,
                    s_ring_storage,
                    sizeof(s_ring_storage));

    __HAL_RCC_DMAMUX1_CLK_ENABLE();
    __HAL_RCC_DMA1_CLK_ENABLE();

    s_hdma_rx.Instance = DMA1_Channel2;
    s_hdma_rx.Init.Request = DMA_REQUEST_LPUART1_RX;
    s_hdma_rx.Init.Direction = DMA_PERIPH_TO_MEMORY;
    s_hdma_rx.Init.PeriphInc = DMA_PINC_DISABLE;
    s_hdma_rx.Init.MemInc = DMA_MINC_ENABLE;
    s_hdma_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    s_hdma_rx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
    s_hdma_rx.Init.Mode = DMA_CIRCULAR;
    s_hdma_rx.Init.Priority = DMA_PRIORITY_LOW;

    st = HAL_DMA_Init(&s_hdma_rx);
    if (st != HAL_OK)
    {
        return st;
    }

    __HAL_LINKDMA(s_uart, hdmarx, s_hdma_rx);

    st = HAL_UART_Receive_DMA(
        s_uart,
        s_dma_buffer,
        (uint16_t)sizeof(s_dma_buffer));

    if (st != HAL_OK)
    {
        return st;
    }

    /*
     * Circular DMA is polled by ProtocolTask. Disable DMA callbacks so no
     * DMA1_Channel2 IRQ handler is needed in this milestone.
     */
    __HAL_DMA_DISABLE_IT(&s_hdma_rx, DMA_IT_HT);
    __HAL_DMA_DISABLE_IT(&s_hdma_rx, DMA_IT_TC);
    __HAL_DMA_DISABLE_IT(&s_hdma_rx, DMA_IT_TE);

    s_dma_last_pos = 0U;
    s_ready = 1U;

    return HAL_OK;
}


void UART_RxDma_Poll(void)
{
    size_t write_pos;

    if ((s_ready == 0U) || (s_uart == NULL))
    {
        return;
    }

    write_pos =
        (size_t)UART_RX_DMA_BUFFER_SIZE -
        (size_t)__HAL_DMA_GET_COUNTER(&s_hdma_rx);

    if (write_pos >= UART_RX_DMA_BUFFER_SIZE)
    {
        write_pos = 0U;
    }

    if (write_pos == s_dma_last_pos)
    {
        return;
    }

    if (write_pos > s_dma_last_pos)
    {
        UART_RxDma_PushChunk(
            &s_dma_buffer[s_dma_last_pos],
            write_pos - s_dma_last_pos);
    }
    else
    {
        UART_RxDma_PushChunk(
            &s_dma_buffer[s_dma_last_pos],
            UART_RX_DMA_BUFFER_SIZE - s_dma_last_pos);

        if (write_pos > 0U)
        {
            UART_RxDma_PushChunk(
                &s_dma_buffer[0],
                write_pos);
        }
    }

    s_dma_last_pos = write_pos;
}


size_t UART_RxDma_Read(uint8_t *dst, size_t max_len)
{
    if ((s_ready == 0U) ||
        (dst == NULL) ||
        (max_len == 0U))
    {
        return 0U;
    }

    return RingBuffer_Read(&s_rx_ring, dst, max_len);
}


uint8_t UART_RxDma_IsReady(void)
{
    return s_ready;
}


size_t UART_RxDma_GetQueuedBytes(void)
{
    return RingBuffer_Count(&s_rx_ring);
}


uint32_t UART_RxDma_GetTotalBytes(void)
{
    return s_total_bytes;
}


uint32_t UART_RxDma_GetDroppedBytes(void)
{
    return s_dropped_bytes;
}
