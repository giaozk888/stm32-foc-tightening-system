#include "uart_async.h"
#include "ring_buffer.h"

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"

#include <string.h>

/*
 * 8 KiB static TX queue.
 * This is BSS, not FreeRTOS heap.
 *
 * Effective capacity is 8191 bytes because the generic ring buffer leaves one
 * slot empty.
 */
#define UART_ASYNC_TX_BUFFER_SIZE       8192U
#define UART_ASYNC_TX_TASK_STACK_WORDS   384U
#define UART_ASYNC_TX_TASK_PRIORITY        2U
#define UART_ASYNC_DMA_IRQ_PRIORITY        6U
#define UART_ASYNC_DMA_TIMEOUT_MS       1000U

static UART_HandleTypeDef *s_uart = NULL;

static DMA_HandleTypeDef s_hdma_tx;

static uint8_t s_tx_storage[UART_ASYNC_TX_BUFFER_SIZE];
static RingBuffer_t s_tx_ring;

static SemaphoreHandle_t s_write_mutex = NULL;
static SemaphoreHandle_t s_data_sem = NULL;
static SemaphoreHandle_t s_dma_done_sem = NULL;

static TaskHandle_t s_tx_task_handle = NULL;

static volatile uint8_t s_ready = 0U;
static volatile uint32_t s_dropped_bytes = 0U;
static volatile uint32_t s_dma_error_count = 0U;


static void UART_Async_TxTask(void *argument)
{
    (void)argument;

    for (;;)
    {
        /*
         * Sleep until at least one producer queued data.
         * A binary semaphore is sufficient because the loop below drains the
         * queue completely before sleeping again.
         */
        (void)xSemaphoreTake(s_data_sem, portMAX_DELAY);

        for (;;)
        {
            const uint8_t *ptr = NULL;
            size_t chunk_len = 0U;

            if (xSemaphoreTake(s_write_mutex,
                               portMAX_DELAY) == pdTRUE)
            {
                chunk_len =
                    RingBuffer_PeekContiguous(&s_tx_ring, &ptr);

                xSemaphoreGive(s_write_mutex);
            }

            if ((chunk_len == 0U) || (ptr == NULL))
            {
                break;
            }

            /*
             * Drain any stale completion token before starting a new DMA
             * transaction.
             */
            (void)xSemaphoreTake(s_dma_done_sem, 0U);

            if (HAL_UART_Transmit_DMA(s_uart,
                                      (uint8_t *)ptr,
                                      (uint16_t)chunk_len) != HAL_OK)
            {
                s_dma_error_count++;
                vTaskDelay(pdMS_TO_TICKS(1U));
                continue;
            }

            /*
             * Only this TX task advances the read/tail side of the ring.
             * The DMA ISR merely signals completion.
             */
            if (xSemaphoreTake(
                    s_dma_done_sem,
                    pdMS_TO_TICKS(UART_ASYNC_DMA_TIMEOUT_MS)) != pdTRUE)
            {
                /*
                 * Avoid permanently wedging the logger if DMA ever stalls.
                 * The timed-out chunk is discarded and accounted as dropped.
                 */
                (void)HAL_UART_AbortTransmit(s_uart);

                s_dma_error_count++;
                s_dropped_bytes += (uint32_t)chunk_len;

                if (xSemaphoreTake(s_write_mutex,
                                   portMAX_DELAY) == pdTRUE)
                {
                    RingBuffer_Consume(&s_tx_ring, chunk_len);
                    xSemaphoreGive(s_write_mutex);
                }

                continue;
            }

            if (xSemaphoreTake(s_write_mutex,
                               portMAX_DELAY) == pdTRUE)
            {
                RingBuffer_Consume(&s_tx_ring, chunk_len);
                xSemaphoreGive(s_write_mutex);
            }
        }
    }
}


HAL_StatusTypeDef UART_Async_Init(UART_HandleTypeDef *huart)
{
    if (s_ready != 0U)
    {
        return HAL_OK;
    }

    if ((huart == NULL) ||
        (huart->Instance != LPUART1))
    {
        return HAL_ERROR;
    }

    s_uart = huart;

    RingBuffer_Init(&s_tx_ring,
                    s_tx_storage,
                    sizeof(s_tx_storage));

    s_write_mutex = xSemaphoreCreateMutex();
    s_data_sem = xSemaphoreCreateBinary();
    s_dma_done_sem = xSemaphoreCreateBinary();

    if ((s_write_mutex == NULL) ||
        (s_data_sem == NULL) ||
        (s_dma_done_sem == NULL))
    {
        return HAL_ERROR;
    }

    /*
     * No other DMA channels are used in the current project.
     * Reserve DMA1 Channel 1 for LPUART1 TX.
     */
    /*
     * STM32G4 DMA requests are routed through DMAMUX1.
     *
     * DMA1 clock alone is NOT sufficient: without the DMAMUX1 clock the
     * LPUART1_TX request does not reach DMA1_Channel1, so
     * HAL_UART_Transmit_DMA() starts but no bytes ever leave the UART.
     */
    __HAL_RCC_DMAMUX1_CLK_ENABLE();
    __HAL_RCC_DMA1_CLK_ENABLE();

    memset(&s_hdma_tx, 0, sizeof(s_hdma_tx));

    s_hdma_tx.Instance = DMA1_Channel1;
    s_hdma_tx.Init.Request = DMA_REQUEST_LPUART1_TX;
    s_hdma_tx.Init.Direction = DMA_MEMORY_TO_PERIPH;
    s_hdma_tx.Init.PeriphInc = DMA_PINC_DISABLE;
    s_hdma_tx.Init.MemInc = DMA_MINC_ENABLE;
    s_hdma_tx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    s_hdma_tx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
    s_hdma_tx.Init.Mode = DMA_NORMAL;
    s_hdma_tx.Init.Priority = DMA_PRIORITY_LOW;

    if (HAL_DMA_Init(&s_hdma_tx) != HAL_OK)
    {
        return HAL_ERROR;
    }

    __HAL_LINKDMA(s_uart, hdmatx, s_hdma_tx);

    /*
     * This IRQ calls FreeRTOS FromISR APIs, so it must NOT be numerically
     * higher priority than configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY (5).
     * Priority 6 is safe with the current FreeRTOSConfig.h.
     */
    HAL_NVIC_SetPriority(DMA1_Channel1_IRQn,
                         UART_ASYNC_DMA_IRQ_PRIORITY,
                         0U);
    HAL_NVIC_EnableIRQ(DMA1_Channel1_IRQn);

    if (xTaskCreate(UART_Async_TxTask,
                    "UartTx",
                    UART_ASYNC_TX_TASK_STACK_WORDS,
                    NULL,
                    UART_ASYNC_TX_TASK_PRIORITY,
                    &s_tx_task_handle) != pdPASS)
    {
        HAL_NVIC_DisableIRQ(DMA1_Channel1_IRQn);
        return HAL_ERROR;
    }

    s_ready = 1U;
    return HAL_OK;
}


uint8_t UART_Async_IsReady(void)
{
    return s_ready;
}


size_t UART_Async_Write(const uint8_t *data, size_t len)
{
    size_t written;

    if ((s_ready == 0U) ||
        (data == NULL) ||
        (len == 0U))
    {
        return 0U;
    }

    /*
     * Zero-wait mutex:
     * logging is never allowed to block a control/application task.
     * If two producers collide for this very short copy section, the later
     * message is dropped and visible through UDROP.
     */
    if (xSemaphoreTake(s_write_mutex, 0U) != pdTRUE)
    {
        s_dropped_bytes += (uint32_t)len;
        return 0U;
    }

    if (RingBuffer_Free(&s_tx_ring) < len)
    {
        s_dropped_bytes += (uint32_t)len;
        xSemaphoreGive(s_write_mutex);
        return 0U;
    }

    written = RingBuffer_Write(&s_tx_ring, data, len);

    xSemaphoreGive(s_write_mutex);

    if (written != len)
    {
        s_dropped_bytes += (uint32_t)(len - written);
        return 0U;
    }

    xSemaphoreGive(s_data_sem);
    return written;
}


size_t UART_Async_WriteString(const char *str)
{
    if (str == NULL)
    {
        return 0U;
    }

    return UART_Async_Write((const uint8_t *)str,
                            strlen(str));
}


size_t UART_Async_GetQueuedBytes(void)
{
    return RingBuffer_Count(&s_tx_ring);
}


uint32_t UART_Async_GetDroppedBytes(void)
{
    return s_dropped_bytes;
}


uint32_t UART_Async_GetDmaErrorCount(void)
{
    return s_dma_error_count;
}


UART_AsyncSelfTestResult_t
UART_Async_RunDirectDmaSelfTest(UART_AsyncSelfTestInfo_t *info)
{
    static uint8_t test_msg[] =
        "UART DIRECT DMA SELFTEST: payload transmitted\r\n";

    HAL_StatusTypeDef st;
    uint32_t i;

    if ((info == NULL) ||
        (s_ready == 0U) ||
        (s_uart == NULL))
    {
        return UART_ASYNC_SELFTEST_START_FAIL;
    }

    memset(info, 0, sizeof(*info));

    info->uart_gstate_before =
        (uint32_t)s_uart->gState;
    info->dma_state_before =
        (uint32_t)HAL_DMA_GetState(&s_hdma_tx);
    info->dma_remaining_before =
        (uint32_t)__HAL_DMA_GET_COUNTER(&s_hdma_tx);
    info->dma_request =
        (uint32_t)s_hdma_tx.Init.Request;

    /*
     * UartTx is lower priority than StartupTask and has no queued data yet,
     * so there is no competing DMA transaction at this point.
     */
    st = HAL_UART_Transmit_DMA(
        s_uart,
        test_msg,
        (uint16_t)(sizeof(test_msg) - 1U));

    info->start_status = st;

    if (st != HAL_OK)
    {
        info->uart_gstate_after =
            (uint32_t)s_uart->gState;
        info->dma_state_after =
            (uint32_t)HAL_DMA_GetState(&s_hdma_tx);
        info->dma_remaining_after =
            (uint32_t)__HAL_DMA_GET_COUNTER(&s_hdma_tx);
        info->dma_ccr =
            (uint32_t)s_hdma_tx.Instance->CCR;
        info->uart_cr3 =
            (uint32_t)s_uart->Instance->CR3;

        return UART_ASYNC_SELFTEST_START_FAIL;
    }

    /*
     * Yield StartupTask while waiting.  This is intentionally NOT HAL_Delay().
     * DMA IRQ/callback and other ready RTOS tasks therefore get CPU time.
     */
    for (i = 0U; i < 100U; i++)
    {
        if (s_uart->gState == HAL_UART_STATE_READY)
        {
            break;
        }

        vTaskDelay(pdMS_TO_TICKS(1U));
    }

    info->uart_gstate_after =
        (uint32_t)s_uart->gState;
    info->dma_state_after =
        (uint32_t)HAL_DMA_GetState(&s_hdma_tx);
    info->dma_remaining_after =
        (uint32_t)__HAL_DMA_GET_COUNTER(&s_hdma_tx);
    info->dma_ccr =
        (uint32_t)s_hdma_tx.Instance->CCR;
    info->uart_cr3 =
        (uint32_t)s_uart->Instance->CR3;

    if (s_uart->gState == HAL_UART_STATE_READY)
    {
        return UART_ASYNC_SELFTEST_PASS;
    }

    /*
     * Restore the proven blocking UART path for the diagnostic report.
     */
    (void)HAL_UART_AbortTransmit(s_uart);

    return UART_ASYNC_SELFTEST_TIMEOUT;
}


/*
 * Strong IRQ handler.  The current project has no DMA IRQ handler yet.
 * If DMA1 Channel 1 is later generated by CubeMX into stm32g4xx_it.c, keep
 * only one definition and let that handler call HAL_DMA_IRQHandler().
 */
void DMA1_Channel1_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&s_hdma_tx);
}


/*
 * HAL weak callback override.
 * Keep the ISR extremely small: just wake the low-priority TX service task.
 */
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    BaseType_t higher_priority_task_woken = pdFALSE;

    if ((s_ready != 0U) &&
        (huart == s_uart))
    {
        xSemaphoreGiveFromISR(
            s_dma_done_sem,
            &higher_priority_task_woken);

        portYIELD_FROM_ISR(higher_priority_task_woken);
    }
}
