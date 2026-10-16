#include "uart_async.h"
#include "uart_tx_pool.h"
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#define UART_ASYNC_TX_TASK_STACK_WORDS 384U
#define UART_ASYNC_TX_TASK_PRIORITY 2U
#define UART_ASYNC_DMA_IRQ_PRIORITY 6U
#define UART_ASYNC_DMA_TIMEOUT_MS 1000U

static UART_HandleTypeDef *s_uart;
static DMA_HandleTypeDef s_hdma_tx;
static SemaphoreHandle_t s_data_sem;
static SemaphoreHandle_t s_dma_done_sem;
static TaskHandle_t s_tx_task_handle;
static volatile uint8_t s_ready;
static atomic_uint s_dropped_bytes;
static atomic_uint s_dma_error_count;
static atomic_uint s_native_frames;
static atomic_uint s_copy_frames;
static atomic_uint s_copied_bytes;
static atomic_uint s_completed_frames;
static atomic_uint s_aborted_frames;
static atomic_uint s_acquire_failures;
static atomic_uint s_format_errors;
static atomic_uint s_shared_frames;
static atomic_uint s_managed_frames;
static atomic_uint s_managed_fallbacks;

static void UART_Async_TxTask(void *argument)
{
    (void)argument;
    for (;;) {
        UartTxMessage message;
        (void)xSemaphoreTake(s_data_sem, portMAX_DELAY);
        while (UartTxPool_Begin(&message)) {
            TickType_t start = xTaskGetTickCount();
            int started = 0;
            (void)xSemaphoreTake(s_dma_done_sem, 0U);
            do {
                if (HAL_UART_Transmit_DMA(s_uart, (uint8_t *)message.data,
                                         (uint16_t)message.length) == HAL_OK) {
                    started = 1;
                    break;
                }
                atomic_fetch_add(&s_dma_error_count, 1U);
                vTaskDelay(pdMS_TO_TICKS(1U));
            } while ((xTaskGetTickCount() - start) <
                      pdMS_TO_TICKS(UART_ASYNC_DMA_TIMEOUT_MS));
            if (!started || (xSemaphoreTake(s_dma_done_sem,
                    pdMS_TO_TICKS(UART_ASYNC_DMA_TIMEOUT_MS)) != pdTRUE)) {
                atomic_fetch_add(&s_dma_error_count, 1U);
                /* Never free a payload while DMA could still access it. */
                if ((HAL_UART_AbortTransmit(s_uart) != HAL_OK) ||
                    ((s_hdma_tx.Instance->CCR & DMA_CCR_EN) != 0U)) {
                    s_ready = 0U;
                    /* Keep this lease pinned, fail closed, no reuse/re-init. */
                    for (;;) vTaskDelay(pdMS_TO_TICKS(100U));
                }
                atomic_fetch_add(&s_dropped_bytes, (unsigned int)message.length);
                atomic_fetch_add(&s_aborted_frames, 1U);
            } else {
                atomic_fetch_add(&s_completed_frames, 1U);
            }
            (void)UartTxPool_Finish(&message);
        }
    }
}

HAL_StatusTypeDef UART_Async_Init(UART_HandleTypeDef *huart)
{
    if (s_ready != 0U)
    {
        return HAL_OK;
    }
    /* A failed task may still pin a DMA lease. Re-init must not erase owners. */
    if (s_tx_task_handle != NULL) return HAL_ERROR;

    if ((huart == NULL) ||
        (huart->Instance != LPUART1))
    {
        return HAL_ERROR;
    }

    s_uart = huart;

    UartTxPool_Init();
    s_data_sem = xSemaphoreCreateBinary();
    s_dma_done_sem = xSemaphoreCreateBinary();

    if ((s_data_sem == NULL) ||
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


int UART_Async_Acquire(size_t capacity, uint32_t timeout_ms,
                       UART_AsyncTxLease_t *lease)
{
    TickType_t start;
    TickType_t timeout;
    if ((s_ready == 0U) || (__get_IPSR() != 0U) || (lease == NULL) ||
        (capacity == 0U) || (capacity > UART_TX_POOL_BYTES)) return 0;
    start = xTaskGetTickCount();
    timeout = pdMS_TO_TICKS(timeout_ms);
    if ((timeout_ms != 0U) && (timeout == 0U)) timeout = 1U;
    do {
        UartTxLease pool = {0};
#if defined(PW_ALLOCATOR_HYBRID)
        if (capacity > UART_TX_POOL_BLOCK_BYTES && capacity <= PW_BUFFER_MAX_BYTES &&
            UartTxPool_Acquire(1U, &pool)) {
            PW_BufferLease managed = {0};
            if (PW_Buffer_Allocate(capacity, PW_BUFFER_UART, &managed)) {
                *lease = (UART_AsyncTxLease_t){managed.data, managed.capacity, pool, managed};
                return 1;
            }
            (void)UartTxPool_Cancel(&pool);
            atomic_fetch_add(&s_managed_fallbacks, 1U);
        }
#endif
        if (UartTxPool_Acquire(capacity, &pool)) {
            *lease = (UART_AsyncTxLease_t){pool.data, pool.capacity, pool, {0}};
            return 1;
        }
        if ((timeout == 0U) || ((xTaskGetTickCount() - start) >= timeout))
            break;
        vTaskDelay(1U);
    } while (s_ready != 0U);
    atomic_fetch_add(&s_acquire_failures, 1U);
    return 0;
}

#if defined(PW_ALLOCATOR_HYBRID)
static void UART_Async_ManagedRelease(uint32_t ref)
{
    /* TX task only, after completion or confirmed DMA stop, never IRQ. */
    (void)PW_Buffer_Release(ref);
}
#endif

static int UART_Async_CommitKind(UART_AsyncTxLease_t *lease,
                                 size_t length, int copied)
{
    if ((s_ready == 0U) || (__get_IPSR() != 0U) || lease == NULL ||
        lease->data == NULL || length == 0U || length > lease->capacity) return 0;
#if defined(PW_ALLOCATOR_HYBRID)
    if (lease->managed.data != NULL) {
        PW_BufferRef ref = 0U;
        const uint8_t *data = lease->managed.data;
        if (lease->data != data || !PW_Buffer_Seal(&lease->managed, &ref)) return 0;
        if (!UartTxPool_CommitReference(&lease->pool, data, length,
                                        UART_Async_ManagedRelease, ref)) {
            (void)PW_Buffer_Release(ref);
            (void)UartTxPool_Cancel(&lease->pool);
            *lease = (UART_AsyncTxLease_t){0};
            return 0;
        }
        atomic_fetch_add(&s_managed_frames, 1U);
    } else
#endif
    {
        if (lease->data != lease->pool.data || !UartTxPool_Commit(&lease->pool, length))
            return 0;
    }
    /* The consumer can already free the payload; never access it again. */
    *lease = (UART_AsyncTxLease_t){0};
    if (copied) {
        atomic_fetch_add(&s_copy_frames, 1U);
        atomic_fetch_add(&s_copied_bytes, (unsigned int)length);
    } else {
        atomic_fetch_add(&s_native_frames, 1U);
    }
    xSemaphoreGive(s_data_sem);
    return 1;
}

int UART_Async_Commit(UART_AsyncTxLease_t *lease, size_t length)
{
    return UART_Async_CommitKind(lease, length, 0);
}

int UART_Async_Cancel(UART_AsyncTxLease_t *lease)
{
    if (__get_IPSR() != 0U || lease == NULL) return 0;
#if defined(PW_ALLOCATOR_HYBRID)
    if (lease->managed.data != NULL && !PW_Buffer_ContextAllowed()) return 0;
#endif
    if (!UartTxPool_Cancel(&lease->pool)) return 0;
#if defined(PW_ALLOCATOR_HYBRID)
    if (lease->managed.data != NULL) (void)PW_Buffer_Cancel(&lease->managed);
#endif
    *lease = (UART_AsyncTxLease_t){0};
    return 1;
}

size_t UART_Async_SubmitReference(const uint8_t *data, size_t length,
                                  UartTxReleaseFn release, uint32_t context,
                                  uint32_t timeout_ms)
{
    UART_AsyncTxLease_t descriptor = {0};
    if (data == NULL || release == NULL || length == 0U || length > UART_TX_POOL_BYTES)
        return 0U;
    if (!UART_Async_Acquire(1U, timeout_ms, &descriptor)) {
        atomic_fetch_add(&s_dropped_bytes, (unsigned int)length);
        return 0U;
    }
    if (s_ready == 0U || __get_IPSR() != 0U ||
        !UartTxPool_CommitReference(&descriptor.pool, data, length, release, context)) {
        (void)UART_Async_Cancel(&descriptor);
        atomic_fetch_add(&s_dropped_bytes, (unsigned int)length);
        return 0U;
    }
    atomic_fetch_add(&s_shared_frames, 1U);
    xSemaphoreGive(s_data_sem);
    return length;
}

static void UART_Async_StaticRelease(uint32_t context) { (void)context; }
size_t UART_Async_WriteStatic(const uint8_t *data, size_t length)
{
    return UART_Async_SubmitReference(data, length, UART_Async_StaticRelease, 0U, 0U);
}

/* Compatibility only: arbitrary caller buffers are copied once into the pool. */
size_t UART_Async_WriteReliable(const uint8_t *data, size_t len,
                                uint32_t timeout_ms)
{
    UART_AsyncTxLease_t lease = {0};
    if ((data == NULL) || (len == 0U) || (len >= UART_TX_POOL_BYTES) ||
        !UART_Async_Acquire(len, timeout_ms, &lease)) {
        if ((data != NULL) && (len != 0U))
            atomic_fetch_add(&s_dropped_bytes, (unsigned int)len);
        return 0U;
    }
    memcpy(lease.data, data, len);
    if (!UART_Async_CommitKind(&lease, len, 1)) {
        (void)UART_Async_Cancel(&lease);
        atomic_fetch_add(&s_dropped_bytes, (unsigned int)len);
        return 0U;
    }
    return len;
}

size_t UART_Async_Write(const uint8_t *data, size_t len)
{
    return UART_Async_WriteReliable(data, len, 0U);
}

size_t UART_Async_WriteString(const char *str)
{
    return (str == NULL) ? 0U :
        UART_Async_Write((const uint8_t *)str, strlen(str));
}

size_t UART_Async_VPrintf(size_t capacity, uint32_t timeout_ms,
                          const char *format, va_list args)
{
    UART_AsyncTxLease_t lease = {0};
    int length;
    if ((format == NULL) || !UART_Async_Acquire(capacity, timeout_ms, &lease))
        return 0U;
    /* Generate directly into final DMA storage, with the requested bound. */
    length = vsnprintf((char *)lease.data, capacity, format, args);
    if ((length <= 0) || ((size_t)length >= capacity)) {
        atomic_fetch_add(&s_format_errors, 1U);
        (void)UART_Async_Cancel(&lease);
        return 0U; /* Never publish a truncated protocol reply. */
    }
    if (!UART_Async_Commit(&lease, (size_t)length)) {
        (void)UART_Async_Cancel(&lease);
        return 0U;
    }
    return (size_t)length;
}

size_t UART_Async_Printf(size_t capacity, uint32_t timeout_ms,
                         const char *format, ...)
{
    size_t length;
    va_list args;
    va_start(args, format);
    length = UART_Async_VPrintf(capacity, timeout_ms, format, args);
    va_end(args);
    return length;
}

size_t UART_Async_GetQueuedBytes(void)
{
    return UartTxPool_QueuedBytes();
}

uint32_t UART_Async_GetDroppedBytes(void)
{
    return atomic_load(&s_dropped_bytes);
}

uint32_t UART_Async_GetDmaErrorCount(void)
{
    return atomic_load(&s_dma_error_count);
}

void UART_Async_GetDiagnostics(UART_AsyncDiagnostics_t *out)
{
    if (out == NULL) return;
    out->native_frames = atomic_load(&s_native_frames);
    out->copy_frames = atomic_load(&s_copy_frames);
    out->copied_bytes = atomic_load(&s_copied_bytes);
    out->completed_frames = atomic_load(&s_completed_frames);
    out->aborted_frames = atomic_load(&s_aborted_frames);
    out->acquire_failures = atomic_load(&s_acquire_failures);
    out->format_errors = atomic_load(&s_format_errors);
    out->reserved_blocks = (uint32_t)UartTxPool_ReservedBlocks();
    out->queued_bytes = (uint32_t)UartTxPool_QueuedBytes();
    out->shared_frames = atomic_load(&s_shared_frames);
    out->managed_frames = atomic_load(&s_managed_frames);
    out->managed_fallbacks = atomic_load(&s_managed_fallbacks);
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
