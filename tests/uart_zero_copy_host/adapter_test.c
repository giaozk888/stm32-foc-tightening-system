/* Tests the real A-slot adapter sources against a deterministic HAL/RTOS.
 * No serial port, board, CAN bus or hardware is opened by this executable. */
#include "uart_async.h"
#include "uart_rx_dma.h"
#include "uart_line_parser.h"
#include "protocol_tx_format.h"
#include "protocol_tx_buffer.h"
#include "tighten_params_storage.h"
#include "task.h"
#include "semphr.h"
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#if defined(PW_ALLOCATOR_HYBRID)
#include "pw_buffer_test_heap.h"
#include "router_uart_tx.h"
#endif

DMA_Channel_TypeDef mock_dma1, mock_dma2;
USART_TypeDef mock_uart;
uint32_t mock_rx_flags, mock_ipsr;
static UART_HandleTypeDef s_uart = {.Instance = LPUART1};
struct MockSemaphore { int token; };
static struct MockSemaphore s_semaphores[2];
static unsigned int s_sem_count;
static TaskFunction_t s_task;
static TickType_t s_tick;
static jmp_buf s_task_exit;
static int s_task_running, s_tx_timeout, s_abort_error, s_tx_busy;
static void (*s_delay_hook)(void);
static const uint8_t *s_tx_pointer;
static uint8_t s_tx_bytes[8192];
static size_t s_tx_length;
static unsigned int s_abort_calls;
static unsigned int s_param_observe, s_param_count;
static char s_param_lines[20][128];
static uint8_t *s_rx_buffer;
static uint16_t s_rx_capacity, s_rx_offset;
static int s_hold_irq, s_overwrite_on_barrier, s_rx_abort_error, s_rx_start_error;

SemaphoreHandle_t xSemaphoreCreateBinary(void)
{
    assert(s_sem_count < 2U);
    return &s_semaphores[s_sem_count++];
}
BaseType_t xSemaphoreTake(SemaphoreHandle_t semaphore, TickType_t ticks)
{
    if (semaphore->token) { semaphore->token = 0; return pdTRUE; }
    if (ticks == portMAX_DELAY) {
        assert(s_task_running);
        longjmp(s_task_exit, 1); /* task idle: stop this deterministic run */
    }
    s_tick += ticks;
    return pdFALSE;
}
BaseType_t xSemaphoreGive(SemaphoreHandle_t semaphore)
{
    semaphore->token = 1;
    return pdTRUE;
}
BaseType_t xSemaphoreGiveFromISR(SemaphoreHandle_t semaphore, BaseType_t *woken)
{
    *woken = pdFALSE;
    return xSemaphoreGive(semaphore);
}
BaseType_t xTaskCreate(TaskFunction_t function, const char *name, uint32_t stack,
                       void *argument, uint32_t priority, TaskHandle_t *handle)
{
    (void)name; (void)stack; (void)argument; (void)priority;
    s_task = function;
    *handle = &s_task;
    return pdPASS;
}
TickType_t xTaskGetTickCount(void) { return s_tick; }
void vTaskDelay(TickType_t ticks)
{
    s_tick += ticks;
    if (s_delay_hook != NULL) s_delay_hook();
    if (s_task_running && ticks == 100U && s_abort_error)
        longjmp(s_task_exit, 2); /* pinned/fail-closed terminal fault */
}
HAL_StatusTypeDef HAL_DMA_Init(DMA_HandleTypeDef *dma)
{
    dma->State = 0U;
    return HAL_OK;
}
uint32_t HAL_DMA_GetState(DMA_HandleTypeDef *dma) { return dma->State; }
void HAL_NVIC_SetPriority(int irq, uint32_t priority, uint32_t subpriority)
{ (void)irq; (void)subpriority; assert(priority == 6U); }
void HAL_NVIC_EnableIRQ(int irq) { (void)irq; }
void HAL_NVIC_DisableIRQ(int irq) { (void)irq; }
HAL_StatusTypeDef HAL_UART_Transmit_DMA(UART_HandleTypeDef *uart, uint8_t *data, uint16_t length)
{
    assert(uart == &s_uart);
    assert(UartTxPool_ReservedBlocks() > 0U);
    if (s_tx_busy > 0) { --s_tx_busy; return HAL_BUSY; }
    s_tx_pointer = data;
    s_tx_length = length;
    memcpy(s_tx_bytes, data, length); /* observation only; not adapter copying */
    if (s_param_observe) {
        assert(s_param_count < 20U && length < sizeof(s_param_lines[0]));
        memcpy(s_param_lines[s_param_count], data, length);
        s_param_lines[s_param_count++][length] = '\0';
    }
    if (length < sizeof(s_tx_bytes)) s_tx_bytes[length] = '\0';
    mock_dma1.CCR |= DMA_CCR_EN;
    if (!s_tx_timeout) {
        mock_dma1.CCR &= ~DMA_CCR_EN;
        HAL_UART_TxCpltCallback(uart);
    }
    return HAL_OK;
}
HAL_StatusTypeDef HAL_UART_AbortTransmit(UART_HandleTypeDef *uart)
{
    assert(uart == &s_uart);
    assert(UartTxPool_ReservedBlocks() > 0U);
    ++s_abort_calls;
    if (s_abort_error) return HAL_ERROR;
    mock_dma1.CCR &= ~DMA_CCR_EN;
    return HAL_OK;
}
HAL_StatusTypeDef HAL_UART_Receive_DMA(UART_HandleTypeDef *uart, uint8_t *data, uint16_t length)
{
    assert(uart == &s_uart);
    if (s_rx_start_error) return HAL_ERROR;
    s_rx_buffer = data; s_rx_capacity = length; s_rx_offset = 0U;
    mock_rx_flags = 0U; mock_dma2.CCR |= DMA_CCR_EN; mock_dma2.CNDTR = length;
    return HAL_OK;
}
HAL_StatusTypeDef HAL_UART_AbortReceive(UART_HandleTypeDef *uart)
{
    assert(uart == &s_uart);
    if (s_rx_abort_error) return HAL_ERROR;
    mock_dma2.CCR &= ~DMA_CCR_EN; mock_rx_flags = 0U;
    return HAL_OK;
}
void HAL_DMA_IRQHandler(DMA_HandleTypeDef *dma)
{
    if (dma->Instance == DMA1_Channel2) {
        if (mock_rx_flags & DMA_FLAG_HT2) {
            mock_rx_flags &= ~DMA_FLAG_HT2;
            HAL_UART_RxHalfCpltCallback(&s_uart);
        }
        if (mock_rx_flags & DMA_FLAG_TC2) {
            mock_rx_flags &= ~DMA_FLAG_TC2;
            HAL_UART_RxCpltCallback(&s_uart);
        }
    }
}
static void FeedByte(uint8_t byte)
{
    assert(mock_dma2.CCR & DMA_CCR_EN);
    s_rx_buffer[s_rx_offset++] = byte;
    if (s_rx_offset == s_rx_capacity / 2U) mock_rx_flags |= DMA_FLAG_HT2;
    if (s_rx_offset == s_rx_capacity) {
        s_rx_offset = 0U; mock_rx_flags |= DMA_FLAG_TC2;
    }
    mock_dma2.CNDTR = s_rx_capacity - s_rx_offset;
    if (mock_rx_flags && !s_hold_irq) DMA1_Channel2_IRQHandler();
}
static void FeedString(const char *text)
{ while (*text != '\0') FeedByte((uint8_t)*text++); }
void mock_barrier(void)
{
    if (s_overwrite_on_barrier) {
        size_t i;
        s_overwrite_on_barrier = 0;
        for (i = 0; i < s_rx_capacity; ++i) FeedByte('x');
    }
}
static int RunTx(void)
{
    int reason;
    s_task_running = 1;
    reason = setjmp(s_task_exit);
    if (reason == 0) s_task(NULL);
    s_task_running = 0;
    return reason;
}
static void TxTests(void)
{
    UART_AsyncTxLease_t lease = {0}, other = {0};
    UART_AsyncDiagnostics_t before, after;
    uint8_t *source;
    char legacy[] = "legacy";
    assert(UART_Async_Init(NULL) == HAL_ERROR);
    assert(UART_Async_Init(&s_uart) == HAL_OK);
    assert(UART_Async_IsReady());
    assert(UART_Async_Acquire(12U, 0U, &lease));
    source = lease.data;
    memcpy(source, "native frame", 12U);
    assert(UART_Async_Commit(&lease, 12U));
    assert(!UART_Async_Commit(&lease, 12U));
    assert(RunTx() == 1);
    assert(s_tx_pointer == source); /* exact producer -> HAL DMA pointer */
    assert(s_tx_length == 12U && memcmp(s_tx_bytes, "native frame", 12U) == 0);
    assert(UartTxPool_ReservedBlocks() == 0U);
    UART_Async_GetDiagnostics(&before);
    assert(before.native_frames == 1U && before.copy_frames == 0U);

    assert(UART_Async_Write((const uint8_t *)legacy, 6U) == 6U);
    memset(legacy, '!', 6U);
    assert(RunTx() == 1);
    assert(memcmp(s_tx_bytes, "legacy", 6U) == 0);
    UART_Async_GetDiagnostics(&after);
    assert(after.copy_frames == 1U && after.copied_bytes == 6U);
    assert(UART_Async_Printf(64U, 0U, "PING %u\r\n", 42U) == 9U);
    assert(RunTx() == 1);
    assert(s_tx_length == 9U && memcmp(s_tx_bytes, "PING 42\r\n", 9U) == 0);
    assert(UART_Async_Printf(4U, 0U, "%s", "truncated") == 0U);
    assert(UartTxPool_ReservedBlocks() == 0U && UartTxPool_QueuedBytes() == 0U);
    UART_Async_GetDiagnostics(&after);
    assert(after.format_errors == 1U && after.copy_frames == 1U);

    assert(UART_Async_Acquire(8192U, 0U, &lease));
    assert(!UART_Async_Acquire(1U, 0U, &other));
    before.acquire_failures = s_tick;
    assert(!UART_Async_Acquire(1U, 3U, &other));
    assert(s_tick - before.acquire_failures == 3U);
    assert(UART_Async_Cancel(&lease));
    mock_ipsr = 1U;
    assert(!UART_Async_Acquire(1U, 0U, &lease));
    mock_ipsr = 0U;

    s_tx_busy = 2;
    assert(UART_Async_Printf(16U, 0U, "retry") == 5U);
    assert(RunTx() == 1 && s_tx_busy == 0);
    assert(memcmp(s_tx_bytes, "retry", 5U) == 0);
    s_tx_timeout = 1;
    assert(UART_Async_Printf(16U, 0U, "timeout") == 7U);
    assert(RunTx() == 1);
    assert(s_abort_calls == 1U && UartTxPool_ReservedBlocks() == 0U);
    UART_Async_GetDiagnostics(&after);
    assert(after.aborted_frames == 1U && after.completed_frames == 4U);
    s_tx_timeout = 0;
    s_tx_busy = 2000; /* permanent HAL_BUSY cannot pin the queue forever */
    before.acquire_failures = s_tick;
    assert(UART_Async_Printf(16U, 0U, "stuck") == 5U);
    assert(RunTx() == 1 && s_tx_busy == 1000);
    assert(s_tick - before.acquire_failures == 1000U);
    assert(s_abort_calls == 2U && UartTxPool_ReservedBlocks() == 0U);
    s_tx_busy = 0;
    puts("PASS: real TX adapter native pointer, legacy copy, formatting, timeout/retry");
}

static unsigned int s_fallback_calls;
static uint8_t s_fallback_ok = 1U;
static char s_fallback_text[512];
static uint8_t CaptureFallback(const char *text)
{
    ++s_fallback_calls;
    assert(strlen(text) < sizeof(s_fallback_text));
    strcpy(s_fallback_text, text); /* synchronous mock Router/boot consumption */
    return s_fallback_ok;
}
static uint8_t SendFormatted(uint8_t native, char *fallback, size_t capacity,
                             const char *format, ...)
{
    uint8_t accepted;
    va_list args;
    va_start(args, format);
    accepted = ProtocolTx_VFormat(native, UART_Async_VPrintf, CaptureFallback,
                                  fallback, capacity, 250U, format, args);
    va_end(args);
    return accepted;
}
static void ProtocolFormatTests(void)
{
    char fallback[384], before_fallback[384];
    UART_AsyncDiagnostics_t before, after;
    UART_AsyncTxLease_t occupied = {0};
    TickType_t start;
    memset(fallback, '!', sizeof(fallback));
    memcpy(before_fallback, fallback, sizeof(fallback));
    UART_Async_GetDiagnostics(&before);
    assert(SendFormatted(1U, fallback, sizeof(fallback),
        "%lu OK FW BEGIN TARGET=%c SIZE=%lu CRC32=0x%08lX\r\n",
        42UL, 'B', 195476UL, 0x547D67EEUL) == 1U);
    assert(memcmp(fallback, before_fallback, sizeof(fallback)) == 0);
    assert(s_fallback_calls == 0U);
    assert(RunTx() == 1);
    assert(s_tx_pointer != (uint8_t *)fallback);
    assert(strcmp((char *)s_tx_bytes,
        "42 OK FW BEGIN TARGET=B SIZE=195476 CRC32=0x547D67EE\r\n") == 0);
    UART_Async_GetDiagnostics(&after);
    assert(after.native_frames == before.native_frames + 1U);
    assert(after.copy_frames == before.copy_frames &&
           after.copied_bytes == before.copied_bytes);

    /* Owns two 256-byte blocks; no hidden 256-byte output limit. */
    char large[301];
    memset(large, 'x', 300U); large[300] = '\0';
    assert(SendFormatted(1U, fallback, sizeof(fallback),
                         "7 OK STATUS %s\r\n", large));
#if defined(PW_ALLOCATOR_HYBRID)
    assert(UartTxPool_ReservedBlocks() == 1U);
#else
    assert(UartTxPool_ReservedBlocks() == 2U);
#endif
    assert(RunTx() == 1 && s_tx_length == 314U);
    assert(UartTxPool_ReservedBlocks() == 0U);
    assert(SendFormatted(1U, NULL, 32U, "%lu OK GET %s=%lu\r\n",
                         9UL, "T1_MS", 300UL));
    assert(RunTx() == 1 && strcmp((char *)s_tx_bytes,
                                  "9 OK GET T1_MS=300\r\n") == 0);

    /* Routed/boot mode retains exact CRLF and propagates synchronous failure. */
    assert(SendFormatted(0U, fallback, sizeof(fallback),
                         "%lu OK GET %s=%lu\r\n", 9UL, "T1_MS", 300UL));
    assert(strcmp(s_fallback_text, "9 OK GET T1_MS=300\r\n") == 0);
    memset(fallback, '?', sizeof(fallback));
    assert(strcmp(s_fallback_text, "9 OK GET T1_MS=300\r\n") == 0);
    s_fallback_ok = 0U;
    assert(!SendFormatted(0U, fallback, sizeof(fallback), "no route"));
    s_fallback_ok = 1U;
    unsigned int calls = s_fallback_calls;
    assert(!SendFormatted(0U, fallback, 4U, "%s", "truncated"));
    assert(!SendFormatted(0U, NULL, 16U, "missing fallback"));
    assert(!SendFormatted(1U, fallback, sizeof(fallback), NULL));
    assert(!SendFormatted(1U, fallback, 0U, "zero"));
    assert(!SendFormatted(1U, fallback, 4U, "%s", "truncated"));
    assert(!SendFormatted(1U, fallback, sizeof(fallback), "%s", ""));
    assert(s_fallback_calls == calls && UartTxPool_QueuedBytes() == 0U);
    assert(UartTxPool_ReservedBlocks() == 0U);

    /* A failed IAP ACK stays failure: no copy/blocking fallback on pool full. */
    assert(UART_Async_Acquire(8192U, 0U, &occupied));
    start = s_tick;
    assert(!SendFormatted(1U, fallback, sizeof(fallback),
                         "%lu OK FW BEGIN TARGET=B\r\n", 42UL));
    assert(s_tick - start == 250U && s_fallback_calls == calls);
    assert(UartTxPool_QueuedBytes() == 0U);
    assert(UART_Async_Cancel(&occupied));
    mock_ipsr = 1U;
    assert(!SendFormatted(1U, fallback, sizeof(fallback), "ISR rejected"));
    mock_ipsr = 0U;
    assert(s_fallback_calls == calls && UartTxPool_ReservedBlocks() == 0U);
    UART_Async_GetDiagnostics(&after);
    assert(after.copy_frames == before.copy_frames &&
           after.copied_bytes == before.copied_bytes);
    puts("PASS: protocol native formatting, unchanged fallback, multi-block STATUS, routed/boot wire, ACK backpressure");
}

static uint8_t SendParamFormatted(char *fallback, size_t capacity,
                                  const char *format, ...)
{
    uint8_t accepted;
    va_list args;
    va_start(args, format);
    accepted = ProtocolTx_VFormat(1U, UART_Async_VPrintf, CaptureFallback,
                                  fallback, capacity, 250U, format, args);
    va_end(args);
    return accepted;
}
static void ParamDmaTests(void)
{
    TightenParamsState_t state = TIGHTEN_PARAMS_STATE_INITIALIZER;
    UART_AsyncDiagnostics_t before, after;
    state.flash_valid = 1U; state.dirty = 1U; state.last_crc32 = 0x224142E1U;
    UART_Async_GetDiagnostics(&before);
    TightenParams_EmitAllFormatted(&state, UINT32_MAX, SendParamFormatted);
    assert(UartTxPool_ReservedBlocks() == 20U);
    s_param_observe = 1U;
    assert(RunTx() == 1);
    s_param_observe = 0U;
    assert(s_param_count == 20U && UartTxPool_ReservedBlocks() == 0U);
    assert(strcmp(s_param_lines[0],
        "4294967295 OK PARAMS BACKEND=PW_KVS FLASH_VALID=1 DIRTY=1 CRC32=0x224142E1\r\n") == 0);
    assert(strcmp(s_param_lines[1], "4294967295 PARAM RUNDOWN_RPM=80\r\n") == 0);
    assert(strcmp(s_param_lines[18], "4294967295 PARAM POST_TRAVEL_MAX_DEG=90\r\n") == 0);
    assert(strcmp(s_param_lines[19], "4294967295 END PARAMS\r\n") == 0);
    UART_Async_GetDiagnostics(&after);
    assert(after.native_frames == before.native_frames + 20U);
    assert(after.copy_frames == before.copy_frames &&
           after.copied_bytes == before.copied_bytes);
    puts("PASS: actual PARAMS emitter generates 20 native DMA frames in order, zero compatibility copies");
}
static void ReplyBufferTests(void)
{
    ProtocolTxBuffer reply = {0};
    UART_AsyncDiagnostics_t before, after;
    char fallback[128];
    memset(fallback, '!', sizeof(fallback));
    UART_Async_GetDiagnostics(&before);
    assert(ProtocolTxBuffer_Begin(&reply, 1U, fallback, sizeof(fallback), 250U));
    char *producer = reply.data;
    int n = snprintf(reply.data, reply.capacity, "%lu OK FAULT SNAPSHOT VALID=0\r\n", 7UL);
    assert(fallback[0] == '!');
    assert(ProtocolTxBuffer_Commit(&reply, n, CaptureFallback));
    assert(reply.data == NULL && reply.capacity == 0U);
    assert(!ProtocolTxBuffer_Commit(&reply, n, CaptureFallback));
    assert(UartTxPool_ReservedBlocks() == 1U); /* commit does NOT free */
    assert(RunTx() == 1 && s_tx_pointer == (uint8_t *)producer);
    assert(strcmp((char *)s_tx_bytes, "7 OK FAULT SNAPSHOT VALID=0\r\n") == 0);
    assert(UartTxPool_ReservedBlocks() == 0U);

    assert(ProtocolTxBuffer_Begin(&reply, 1U, fallback, 4U, 0U));
    assert(!ProtocolTxBuffer_Commit(&reply, 4, CaptureFallback));
    assert(UartTxPool_ReservedBlocks() == 0U);
    assert(ProtocolTxBuffer_Begin(&reply, 1U, fallback, sizeof(fallback), 0U));
    ProtocolTxBuffer_Cancel(&reply); /* caller rejects length before publish */
    ProtocolTxBuffer_Cancel(&reply); /* no stale owner/double free */
    assert(UartTxPool_ReservedBlocks() == 0U);
    assert(ProtocolTxBuffer_Begin(&reply, 0U, fallback, sizeof(fallback), 0U));
    n = snprintf(reply.data, reply.capacity, "routed snapshot\r\n");
    assert(ProtocolTxBuffer_Commit(&reply, n, CaptureFallback));
    assert(strcmp(s_fallback_text, "routed snapshot\r\n") == 0);
    assert(!ProtocolTxBuffer_Begin(&reply, 0U, NULL, 128U, 0U));
    assert(!ProtocolTxBuffer_Begin(&reply, 1U, fallback, 0U, 0U));
    mock_ipsr = 1U;
    assert(!ProtocolTxBuffer_Begin(&reply, 1U, fallback, 128U, 0U));
    mock_ipsr = 0U;
    UART_Async_GetDiagnostics(&after);
    assert(after.native_frames == before.native_frames + 1U &&
           after.copy_frames == before.copy_frames);
    puts("PASS: checked reply builder producer==DMA address, cancel/truncation, ownership pin until completion");
}
typedef struct {
    UartLineParser parser;
    char lines[16][UART_LINE_CAPACITY];
    size_t count, bytes, gaps;
} Receiver;
static void OnLine(const char *line, void *context)
{
    Receiver *receiver = context;
    assert(receiver->count < 16U);
    strcpy(receiver->lines[receiver->count++], line);
}
static void OnByte(uint8_t byte, void *context)
{
    Receiver *receiver = context;
    ++receiver->bytes;
    (void)UartLineParser_Byte(&receiver->parser, byte, OnLine, receiver);
}
static void OnGap(void *context)
{
    Receiver *receiver = context;
    ++receiver->gaps;
    UartLineParser_Gap(&receiver->parser);
}
static size_t Drain(Receiver *receiver)
{ return UART_RxDma_Drain(OnByte, OnGap, receiver, 4096U); }
static void RxTests(void)
{
    Receiver receiver = {0};
    size_t i, bytes_before;
    uint32_t restarts;
    uint8_t copied[4];
    assert(UART_RxDma_Init(NULL) == HAL_ERROR);
    assert(UART_RxDma_Init(&s_uart) == HAL_OK && s_rx_capacity == 1024U);
    UartLineParser_Init(&receiver.parser);
    FeedString("PING\r\n");
    assert(Drain(&receiver) == 6U);
    assert(receiver.count == 1U && strcmp(receiver.lines[0], "PING") == 0);

    FeedString("PARTIAL"); Drain(&receiver);
    for (i = 0U; i < 1100U; ++i) FeedByte('x'); /* timely IRQs, late consumer */
    assert(Drain(&receiver) == 0U && receiver.gaps == 1U);
    assert(UART_RxDma_GetDroppedBytes() >= 1100U);
    FeedString("UNSAFE SUFFIX\nPING2\n"); Drain(&receiver);
    assert(receiver.count == 2U && strcmp(receiver.lines[1], "PING2") == 0);

    restarts = UART_RxDma_GetRestartCount();
    s_hold_irq = 1;
    for (i = 0U; i < 1200U; ++i) FeedByte('y');
    assert(Drain(&receiver) == 0U);
    assert(!UART_RxDma_IsReady() && UART_RxDma_GetAmbiguousCount() == 1U);
    s_hold_irq = 0;
    Drain(&receiver); /* deferred abort/restart then gap delivery */
    assert(UART_RxDma_GetRestartCount() == restarts + 1U && UART_RxDma_IsReady());
    FeedString("SUFFIX\nPING3\n"); Drain(&receiver);
    assert(receiver.count == 3U && strcmp(receiver.lines[2], "PING3") == 0);

    FeedString("Z");
    bytes_before = receiver.bytes;
    s_overwrite_on_barrier = 1;
    assert(Drain(&receiver) == 0U && receiver.bytes == bytes_before);
    FeedString("\nPING4\n"); Drain(&receiver);
    assert(receiver.count == 4U && strcmp(receiver.lines[3], "PING4") == 0);

    FeedString("ERROR PARTIAL"); Drain(&receiver);
    s_uart.ErrorCode = 8U;
    HAL_UART_ErrorCallback(&s_uart);
    s_rx_abort_error = 1;
    Drain(&receiver);
    assert(UART_RxDma_GetRestartFailureCount() == 1U && !UART_RxDma_IsReady());
    s_rx_abort_error = 0; s_rx_start_error = 1;
    Drain(&receiver);
    assert(UART_RxDma_GetRestartFailureCount() == 2U);
    s_rx_start_error = 0;
    Drain(&receiver);
    assert(UART_RxDma_IsReady() && UART_RxDma_GetLastError() == 8U);
    FeedString("SUFFIX\nPING5\n"); Drain(&receiver);
    assert(receiver.count == 5U && strcmp(receiver.lines[4], "PING5") == 0);
    FeedString("abc");
    assert(UART_RxDma_Read(copied, sizeof(copied)) == 3U);
    assert(memcmp(copied, "abc", 3U) == 0);
    puts("PASS: real RX adapter direct parser, overrun/ambiguous IRQ/error resync, late overwrite");
}
static void TxPinnedFault(void)
{
    UART_AsyncTxLease_t lease = {0};
    s_tx_timeout = 1; s_abort_error = 1;
#if defined(PW_ALLOCATOR_HYBRID)
    assert(UART_Async_Printf(512U, 0U, "pin") == 3U);
#else
    assert(UART_Async_Printf(16U, 0U, "pin") == 3U);
#endif
    assert(RunTx() == 2);
    assert(!UART_Async_IsReady());
    assert(UartTxPool_ReservedBlocks() == 1U && UartTxPool_QueuedBytes() == 3U);
    assert(mock_dma1.CCR & DMA_CCR_EN);
    assert(!UART_Async_Acquire(1U, 0U, &lease));
    assert(UART_Async_Init(&s_uart) == HAL_ERROR);
    assert(UartTxPool_ReservedBlocks() == 1U);
#if defined(PW_ALLOCATOR_HYBRID)
    PW_BufferDiagnostics stats = {0};
    PW_Buffer_GetDiagnostics(&stats);
    assert(stats.live_objects == 1U && stats.live_bytes == 512U);
    assert(PW_BufferTest_LiveAllocations() == 1U);
#endif
    puts("PASS: abort failure pins DMA owner, disables TX and rejects unsafe re-init");
}
#if defined(PW_ALLOCATOR_HYBRID)
static void HybridTests(void)
{
    UART_AsyncTxLease_t lease = {0}, stale;
    PW_BufferDiagnostics stats = {0};
    UART_AsyncDiagnostics_t before, after;
    assert(UART_Async_Acquire(513U, 0U, &lease));
    assert(lease.managed.data == lease.data && lease.capacity == 513U);
    assert(UartTxPool_ReservedBlocks() == 1U);
    uint8_t *producer = lease.data;
    memset(producer, 0xD4, lease.capacity);
    stale = lease;
    assert(!UART_Async_Commit(&lease, 514U)); // writer still owns on bad length
    assert(UART_Async_Commit(&lease, 513U));
    assert(!UART_Async_Cancel(&stale) && !UART_Async_Commit(&stale, 513U));
    PW_Buffer_GetDiagnostics(&stats);
    assert(stats.live_objects == 1U && stats.live_bytes == 513U);
    assert(RunTx() == 1 && s_tx_pointer == producer && s_tx_bytes[512] == 0xD4);
    assert(PW_BufferTest_LiveAllocations() == 0U);
    assert(UART_Async_Acquire(513U, 0U, &lease));
    assert(!UART_Async_Cancel(&stale)); // old token cannot cancel reused heap slot
    PW_BufferTest_SetContext(0, 1, 4);
    assert(!UART_Async_Cancel(&lease)); // rejected without losing the descriptor
    PW_BufferTest_SetContext(0, 1, 1);
    assert(UART_Async_Cancel(&lease));
    assert(PW_BufferTest_LiveAllocations() == 0U);
    assert(UART_Async_Acquire(513U, 0U, &lease));
    assert(UartTxPool_Cancel(&lease.pool)); /* fault injection: descriptor invalid */
    assert(!UART_Async_Commit(&lease, 513U));
    assert(lease.data == NULL && PW_BufferTest_LiveAllocations() == 0U);
    char too_long[600]; memset(too_long, 'x', sizeof(too_long) - 1U); too_long[599] = '\0';
    assert(UART_Async_Printf(513U, 0U, "%s", too_long) == 0U);
    assert(PW_BufferTest_LiveAllocations() == 0U && UartTxPool_ReservedBlocks() == 0U);
    UART_Async_GetDiagnostics(&before);
    PW_BufferTest_SetFreeHeap(PW_BUFFER_HEAP_RESERVE);
    assert(UART_Async_Acquire(513U, 0U, &lease));
    assert(lease.managed.data == NULL && UartTxPool_ReservedBlocks() == 3U);
    assert(UART_Async_Cancel(&lease));
    PW_BufferTest_SetFreeHeap(40U * 1024U);
    PW_BufferTest_FailAllocation(1);
    assert(UART_Async_Acquire(513U, 0U, &lease) && lease.managed.data == NULL);
    assert(UART_Async_Cancel(&lease));
    PW_BufferTest_FailAllocation(0);
    UART_Async_GetDiagnostics(&after);
    assert(after.managed_fallbacks == before.managed_fallbacks + 2U);
    assert(UART_Async_Printf(512U, 0U, "aborted") == 7U);
    s_tx_timeout = 1;
    assert(RunTx() == 1 && PW_BufferTest_LiveAllocations() == 0U);
    s_tx_timeout = 0;
    assert(UartTxPool_ReservedBlocks() == 0U);
    puts("PASS: hybrid producer==DMA, immutable pin, cancel/stale, heap reserve/OOM fallback, abort cleanup");
    RouterPacket_t packet = {0};
    packet.src = UINT16_MAX; packet.dst = UINT16_MAX; packet.seq = UINT16_MAX;
    packet.ttl = UINT8_MAX; packet.type = UINT8_MAX;
    for (unsigned i = 0; i < 3U; ++i) {
        packet.length = (uint16_t)(i == 0 ? 0 : i == 1 ? 160 : ROUTER_MAX_PAYLOAD);
        memset(packet.payload, 'x', packet.length); packet.payload[packet.length] = '\0';
        char expected[ROUTER_MAX_PAYLOAD + 96U];
        expected[0] = '\r'; expected[1] = '\n';
        size_t length = Router_EncodeAsciiFrame(&packet, expected + 2U, sizeof(expected) - 2U);
        expected[length + 2] = '\r'; expected[length + 3] = '\n'; expected[length + 4] = '\0';
        assert(RouterUartTx_Queue(&packet, 0U));
        PW_Buffer_GetDiagnostics(&stats);
        assert(stats.live_objects == (i == 2U ? 1U : 0U));
        assert(RunTx() == 1 && s_tx_length == length + 4U);
        assert(memcmp(s_tx_bytes, expected, length + 4U) == 0);
        assert(PW_BufferTest_LiveAllocations() == 0U);
    }
    packet.length = ROUTER_MAX_PAYLOAD + 1U;
    assert(!RouterUartTx_Queue(&packet, 0U) && !RouterUartTx_Queue(NULL, 0U));
    puts("PASS: actual A/B Router encoder, min/boundary/max R1 + CRLF, medium heap payload, no wire changes");
}
#endif
int main(void)
{
    TxTests(); ProtocolFormatTests(); ParamDmaTests(); ReplyBufferTests();
    RxTests();
#if defined(PW_ALLOCATOR_HYBRID)
    HybridTests();
#endif
    TxPinnedFault();
    return 0;
}
