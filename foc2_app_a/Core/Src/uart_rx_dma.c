#include "uart_rx_dma.h"
#include "uart_rx_cursor.h"
#include <stdatomic.h>
#include <string.h>

#define UART_RX_DMA_BUFFER_SIZE 1024U
#define UART_RX_DMA_IRQ_PRIORITY 6U
static UART_HandleTypeDef *s_uart;
static DMA_HandleTypeDef s_hdma_rx;
_Alignas(4) static uint8_t s_dma_buffer[UART_RX_DMA_BUFFER_SIZE];
static atomic_uint s_half_events;
static UartRxCursor s_cursor;
static uint32_t s_delivered_gap;
static volatile uint8_t s_ready;
static volatile uint8_t s_restart_requested;
volatile uint32_t g_uart_rx_dma_error_count;
volatile uint32_t g_uart_rx_dma_last_error;
volatile uint32_t g_uart_rx_dma_restart_count;
volatile uint32_t g_uart_rx_dma_restart_failure_count;
volatile uint32_t g_uart_rx_dma_ambiguous_count;

/* If both boundary flags accumulated, interrupt latency is ambiguous. Sticky
 * DMA flags cannot count arbitrary laps. Fail closed and resync, not guess. */
static int UART_RxDma_Ambiguous(void)
{
    if ((__HAL_DMA_GET_FLAG(&s_hdma_rx, DMA_FLAG_HT2) != 0U) &&
        (__HAL_DMA_GET_FLAG(&s_hdma_rx, DMA_FLAG_TC2) != 0U)) {
        if (s_ready != 0U) ++g_uart_rx_dma_ambiguous_count;
        s_ready = 0U;
        s_restart_requested = 1U;
        return 1;
    }
    return 0;
}

static int UART_RxDma_Position(uint32_t *out)
{
    unsigned int first;
    unsigned int second;
    uint32_t position;
    do {
        if ((s_ready == 0U) || UART_RxDma_Ambiguous()) return 0;
        first = atomic_load_explicit(&s_half_events, memory_order_acquire);
        position = UART_RX_DMA_BUFFER_SIZE -
                   (uint32_t)__HAL_DMA_GET_COUNTER(&s_hdma_rx);
        second = atomic_load_explicit(&s_half_events, memory_order_acquire);
    } while (first != second);
    if (position >= UART_RX_DMA_BUFFER_SIZE) position = 0U;
    if ((s_ready == 0U) || UART_RxDma_Ambiguous()) return 0;
    *out = UartRxCursor_Position(first, position, UART_RX_DMA_BUFFER_SIZE);
    return 1;
}

static HAL_StatusTypeDef UART_RxDma_Start(void)
{
    HAL_StatusTypeDef status;
    atomic_store(&s_half_events, 0U);
    s_cursor.consumed = 0U;
    s_cursor.produced = 0U;
    status = HAL_UART_Receive_DMA(s_uart, s_dma_buffer,
                                  (uint16_t)sizeof(s_dma_buffer));
    s_ready = (status == HAL_OK) ? 1U : 0U;
    return status;
}

static void UART_RxDma_ServiceRecovery(void)
{
    if ((s_restart_requested == 0U) || (s_uart == NULL)) return;
    s_restart_requested = 0U;
    s_ready = 0U;
    UartRxCursor_Gap(&s_cursor);
    if ((HAL_UART_AbortReceive(s_uart) != HAL_OK) ||
        (UART_RxDma_Start() != HAL_OK)) {
        ++g_uart_rx_dma_restart_failure_count;
        s_restart_requested = 1U;
    } else {
        ++g_uart_rx_dma_restart_count;
    }
}

HAL_StatusTypeDef UART_RxDma_Init(UART_HandleTypeDef *uart)
{
    HAL_StatusTypeDef status;
    if ((uart == NULL) || (uart->Instance != LPUART1)) return HAL_ERROR;
    s_ready = 0U;
    s_restart_requested = 0U;
    s_uart = uart;
    UartRxCursor_Init(&s_cursor, UART_RX_DMA_BUFFER_SIZE);
    s_delivered_gap = 0U;
    atomic_init(&s_half_events, 0U);
    g_uart_rx_dma_error_count = 0U;
    g_uart_rx_dma_last_error = 0U;
    g_uart_rx_dma_restart_count = 0U;
    g_uart_rx_dma_restart_failure_count = 0U;
    g_uart_rx_dma_ambiguous_count = 0U;
    memset(&s_hdma_rx, 0, sizeof(s_hdma_rx));
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
    status = HAL_DMA_Init(&s_hdma_rx);
    if (status != HAL_OK) return status;
    __HAL_LINKDMA(s_uart, hdmarx, s_hdma_rx);
    HAL_NVIC_SetPriority(DMA1_Channel2_IRQn, UART_RX_DMA_IRQ_PRIORITY, 0U);
    HAL_NVIC_EnableIRQ(DMA1_Channel2_IRQn);
    return UART_RxDma_Start();
}

void UART_RxDma_Poll(void)
{
    uint32_t produced;
    UART_RxDma_ServiceRecovery();
    if ((s_uart != NULL) && UART_RxDma_Position(&produced))
        (void)UartRxCursor_Update(&s_cursor, produced);
}

/* Copy no bulk buffers: load one byte from DMA memory into a register, verify
 * it was not overwritten, consume it, then hand it to the synchronous parser.
 * No pointer into live circular DMA storage escapes this call. */
size_t UART_RxDma_Drain(UART_RxDma_ByteFn byte_fn, UART_RxDma_GapFn gap_fn,
                        void *context, size_t budget)
{
    size_t count = 0U;
    if ((byte_fn == NULL) || (budget == 0U)) return 0U;
    UART_RxDma_Poll();
    while (count < budget) {
        uint32_t produced;
        uint32_t cursor;
        uint8_t byte;
        if (s_delivered_gap != s_cursor.gaps) {
            s_delivered_gap = s_cursor.gaps;
            if (gap_fn != NULL) gap_fn(context);
        }
        if (!UART_RxDma_Position(&produced)) break;
        if (UartRxCursor_Update(&s_cursor, produced) == 0U) {
            if (s_delivered_gap != s_cursor.gaps) continue;
            break;
        }
        cursor = s_cursor.consumed;
        byte = ((const volatile uint8_t *)s_dma_buffer)[cursor % UART_RX_DMA_BUFFER_SIZE];
        __DMB();
        if (!UART_RxDma_Position(&produced)) break;
        (void)UartRxCursor_Update(&s_cursor, produced);
        if ((s_cursor.consumed != cursor) || (s_ready == 0U)) continue;
        ++s_cursor.consumed;
        ++count;
        byte_fn(byte, context);
    }
    return count;
}

typedef struct { uint8_t *out; size_t length; } CopyContext;
static void UART_RxDma_CopyByte(uint8_t byte, void *context)
{
    CopyContext *copy = (CopyContext *)context;
    copy->out[copy->length++] = byte;
}

size_t UART_RxDma_Read(uint8_t *out, size_t capacity)
{
    CopyContext copy = {out, 0U};
    if (out == NULL) return 0U;
    (void)UART_RxDma_Drain(UART_RxDma_CopyByte, NULL, &copy, capacity);
    return copy.length;
}

uint8_t UART_RxDma_IsReady(void) { return s_ready; }
size_t UART_RxDma_GetQueuedBytes(void) { return s_cursor.produced - s_cursor.consumed; }
uint32_t UART_RxDma_GetTotalBytes(void) { return s_cursor.total; }
uint32_t UART_RxDma_GetDroppedBytes(void) { return s_cursor.dropped; }
uint32_t UART_RxDma_GetGapCount(void) { return s_cursor.gaps; }
uint32_t UART_RxDma_GetAmbiguousCount(void) { return g_uart_rx_dma_ambiguous_count; }
uint32_t UART_RxDma_GetErrorCount(void) { return g_uart_rx_dma_error_count; }
uint32_t UART_RxDma_GetLastError(void) { return g_uart_rx_dma_last_error; }
uint32_t UART_RxDma_GetRestartCount(void) { return g_uart_rx_dma_restart_count; }
uint32_t UART_RxDma_GetRestartFailureCount(void) { return g_uart_rx_dma_restart_failure_count; }
uint32_t UART_RxDma_GetDmaState(void) { return (uint32_t)HAL_DMA_GetState(&s_hdma_rx); }
uint32_t UART_RxDma_GetDmaRemaining(void) { return (uint32_t)__HAL_DMA_GET_COUNTER(&s_hdma_rx); }
uint32_t UART_RxDma_GetUartRxState(void) { return s_uart ? (uint32_t)s_uart->RxState : 0U; }
uint32_t UART_RxDma_GetUartCr3(void) { return s_uart ? s_uart->Instance->CR3 : 0U; }

void DMA1_Channel2_IRQHandler(void)
{
    (void)UART_RxDma_Ambiguous();
    HAL_DMA_IRQHandler(&s_hdma_rx);
}

void HAL_UART_RxHalfCpltCallback(UART_HandleTypeDef *uart)
{
    if ((uart == s_uart) && s_ready)
        atomic_fetch_add_explicit(&s_half_events, 1U, memory_order_release);
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *uart)
{
    if ((uart == s_uart) && s_ready)
        atomic_fetch_add_explicit(&s_half_events, 1U, memory_order_release);
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *uart)
{
    if (uart != s_uart) return;
    ++g_uart_rx_dma_error_count;
    g_uart_rx_dma_last_error = uart->ErrorCode;
    s_ready = 0U;
    s_restart_requested = 1U;
}
