/* Real A/B UART and Pigweed adapters with deterministic HAL/RTOS only.
 * Reuse baseline mock drivers; never open a device or run motor commands. */
#define main uart_baseline_main
#include "adapter_test.c"
#undef main
#include "pw_log_backend.h"
#include "pw_log_router_bridge.h"
#include "pw_can_log.h"
#include "can_log_v1.h"
#include "queue.h"
#include "pw_log_snapshot.h"
#include <stdarg.h>

static TaskFunction_t s_log_task;
static jmp_buf s_log_exit;
static size_t s_queues_created, s_router_sends, s_can_frames;
static int s_route_fail, s_can_busy;
static const char *s_router_pointer;
static size_t s_router_length;
static uint32_t s_reference_released;
static CanLog_Start s_can_start;
static uint8_t s_can_text[CAN_LOG_MAX_TEXT];
static size_t s_can_received;
static uint32_t s_can_complete, s_can_queue_drops, s_can_stale_drops;

TaskHandle_t xTaskCreateStatic(TaskFunction_t function, const char *name,
                              uint32_t stack, void *argument, uint32_t priority,
                              StackType_t *buffer, StaticTask_t *control)
{
    (void)name; (void)stack; (void)argument; (void)priority; (void)buffer;
    s_log_task = function; return control;
}
QueueHandle_t xQueueCreateStatic(UBaseType_t depth, UBaseType_t item_size,
                                 uint8_t *storage, StaticQueue_t *control)
{
    /* All three queues must carry only references/metadata, never a 192B log. */
    assert(item_size <= 16U);
    *control = (StaticQueue_t){depth, item_size, 0U, 0U, storage};
    ++s_queues_created; return control;
}
BaseType_t xQueueSend(QueueHandle_t queue, const void *item, TickType_t ticks)
{
    (void)ticks;
    if (queue->count == queue->depth) return pdFALSE;
    size_t position = (queue->head + queue->count) % queue->depth;
    memcpy(queue->storage + position * queue->item_size, item, queue->item_size);
    ++queue->count; return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t queue, void *item, TickType_t ticks)
{
    if (!queue->count) {
        if (ticks == portMAX_DELAY) longjmp(s_log_exit, 1);
        return pdFALSE;
    }
    memcpy(item, queue->storage + queue->head * queue->item_size, queue->item_size);
    queue->head = (queue->head + 1U) % queue->depth;
    --queue->count; return pdTRUE;
}
UBaseType_t uxQueueMessagesWaiting(QueueHandle_t queue) { return (UBaseType_t)queue->count; }
uint32_t HAL_GetTick(void) { return s_tick; }
uint32_t PW_Log_TestInterruptState(void) { return mock_ipsr; }
uint8_t CAN_StatusTx_TryLogFrame(uint32_t id, const uint8_t data[8])
{
    assert(id == CAN_LOG_START_ID || id == CAN_LOG_DATA_ID || id == CAN_LOG_STATS_ID);
    assert(data != NULL);
    if (s_can_busy) return 0U;
    if (id == CAN_LOG_STATS_ID) {
        s_can_queue_drops = data[2] | ((uint32_t)data[3] << 8);
        s_can_stale_drops = data[4] | ((uint32_t)data[5] << 8);
    } else if (id == CAN_LOG_START_ID) {
        assert(CanLog_DecodeStart(data, &s_can_start));
        s_can_received = 0U;
    } else {
        assert((data[0] | ((uint32_t)data[1] << 8)) == s_can_start.record_id);
        assert((size_t)data[2] * CAN_LOG_CHUNK_SIZE == s_can_received);
        size_t count = s_can_start.length - s_can_received;
        if (count > CAN_LOG_CHUNK_SIZE) count = CAN_LOG_CHUNK_SIZE;
        memcpy(s_can_text + s_can_received, data + 3, count);
        s_can_received += count;
        if (s_can_received == s_can_start.length) {
            assert(CanLog_Crc16(s_can_text, s_can_received) == s_can_start.crc);
            ++s_can_complete;
        }
    }
    ++s_can_frames; return 1U;
}
uint8_t Router_SendSpan(uint16_t dst, uint8_t type, const char *payload,
                        size_t length, uint16_t *seq)
{
    assert(dst == 2U && type == PW_LOG_ROUTER_PACKET_TYPE && length > 0U);
    assert(payload[length - 1U] != '\r' && payload[length - 1U] != '\n');
    s_router_pointer = payload; s_router_length = length; ++s_router_sends;
    *seq = 1U; return s_route_fail ? 0U : 1U;
}
static void RunLogs(void)
{
    if (setjmp(s_log_exit) == 0) s_log_task(NULL);
}
static void ClearDuringWait(void) { s_delay_hook = NULL; PW_Log_Clear(); }
static void Released(uint32_t value) { assert(value == 42U); ++s_reference_released; }
static void DropStaleCan(void)
{
    s_tick += 11000U;
    for (uint32_t i = 0U; i < 20U; ++i) { s_tick += 100U; PW_CanLog_Service(s_tick); }
}
static void LogPrintf(int level, const char *module, const char *format, ...)
{
    extern void pw_log_string_HandleMessageVaList(int, unsigned int, const char *,
                                                 const char *, int, const char *, va_list);
    va_list args;
    va_start(args, format);
    pw_log_string_HandleMessageVaList(level, 0U, module, "host", 1, format, args);
    va_end(args);
}
static void ReferenceTests(void)
{
    static const uint8_t data[] = "shared immutable";
    UART_AsyncDiagnostics_t before, after;
    UART_Async_GetDiagnostics(&before);
    assert(UART_Async_SubmitReference(data, sizeof(data) - 1U, Released, 42U, 0U) == sizeof(data) - 1U);
    assert(s_reference_released == 0U);
    assert(RunTx() == 1 && s_tx_pointer == data && s_reference_released == 1U);
    assert(UART_Async_WriteStatic(data, sizeof(data) - 1U) == sizeof(data) - 1U);
    assert(RunTx() == 1 && s_tx_pointer == data);
    s_tx_timeout = 1;
    assert(UART_Async_SubmitReference(data, sizeof(data) - 1U, Released, 42U, 0U) == sizeof(data) - 1U);
    assert(RunTx() == 1 && s_reference_released == 2U); /* confirmed abort releases */
    s_tx_timeout = 0;
    UART_Async_GetDiagnostics(&after);
    assert(after.shared_frames == before.shared_frames + 3U);
    assert(after.copied_bytes == before.copied_bytes);
    assert(!UART_Async_SubmitReference(data, 0U, Released, 42U, 0U));
    assert(!UART_Async_SubmitReference(data, 1U, NULL, 42U, 0U));
    mock_ipsr = 1U;
    assert(!UART_Async_SubmitReference(data, sizeof(data) - 1U, Released, 42U, 0U));
    mock_ipsr = 0U; assert(s_reference_released == 2U);
    UART_AsyncTxLease_t held[UART_TX_POOL_BLOCKS];
    for (size_t i = 0U; i < UART_TX_POOL_BLOCKS; ++i)
        assert(UART_Async_Acquire(1U, 0U, &held[i]));
    assert(!UART_Async_SubmitReference(data, sizeof(data) - 1U, Released, 42U, 0U));
    assert(s_reference_released == 2U); /* failed submit did not consume owner */
    for (size_t i = 0U; i < UART_TX_POOL_BLOCKS; ++i) assert(UART_Async_Cancel(&held[i]));
}
static void HistoryTests(void)
{
    PW_LogDiagnostics_t diag;
    UART_AsyncDiagnostics_t before, after;
    assert(PW_Log_Init() && PW_LogRouter_Init() && PW_CanLog_Init());
    assert(s_queues_created == 3U);
    assert(PW_LogRouter_Subscribe(2U, PW_LOG_RUNTIME_DEBUG, 3600U));
    assert(PW_Log_TestBurst(1U) == 1U);
    RunLogs();
    PW_LogRouter_Service(1U);
    const char *address = s_router_pointer;
    size_t length = s_router_length + 2U;
    assert(s_router_sends == 1U && PwLogStore_Used() == 1U);
    PW_Log_Clear(); /* UART and CAN still own exactly the same immutable record */
    assert(PwLogStore_Used() == 1U);
    assert(RunTx() == 1 && (const char *)s_tx_pointer == address && s_tx_length == length);
    assert(PwLogStore_Used() == 1U); /* CAN not finished yet */
    for (uint32_t i = 1U; i < 30U; ++i) { s_tick += 100U; PW_CanLog_Service(s_tick); }
    assert(s_can_frames > 1U && s_can_complete == 1U && PwLogStore_Used() == 0U);
    assert(s_can_received == length - 2U && !memcmp(s_can_text, s_tx_bytes, length - 2U));

    /* Mirror queue overflow drops only its attempted owner. Busy CAN pins its
     * accepted owners; failed/filtered/expired Router deliveries release theirs. */
    PW_LogRouterDiagnostics_t route_before, route_after;
    PW_LogRouter_GetDiagnostics(&route_before);
    assert(PW_Log_TestBurst(24U) == 24U); RunLogs();
    PW_LogRouter_GetDiagnostics(&route_after);
    assert(route_after.queued == 8U && route_after.queue_dropped == route_before.queue_dropped + 16U);
    PW_Log_Clear(); assert(RunTx() == 1 && PwLogStore_Used() == 8U);
    s_route_fail = 1; PW_LogRouter_Service(4U); s_route_fail = 0;
    PW_LogRouter_Service(4U);
    PW_LogRouter_GetDiagnostics(&route_after);
    assert(route_after.queued == 0U && route_after.route_failed == route_before.route_failed + 4U);
    assert(PwLogStore_Used() == 8U);
    s_can_busy = 1; s_tick += 100U; PW_CanLog_Service(s_tick);
    assert(PwLogStore_Used() == 8U); s_can_busy = 0;
    DropStaleCan(); assert(PwLogStore_Used() == 0U);
    assert(s_can_queue_drops == 16U && s_can_stale_drops == 8U);

    assert(PW_LogRouter_Subscribe(2U, PW_LOG_RUNTIME_ERROR, 3600U));
    assert(PW_Log_TestBurst(1U) == 1U); RunLogs(); PW_Log_Clear(); assert(RunTx() == 1);
    PW_LogRouter_Service(1U); PW_LogRouter_GetDiagnostics(&route_after);
    assert(route_after.level_filtered == route_before.level_filtered + 1U);
    DropStaleCan(); assert(PwLogStore_Used() == 0U);
    assert(PW_LogRouter_Subscribe(2U, PW_LOG_RUNTIME_DEBUG, 1U));
    assert(PW_Log_TestBurst(1U) == 1U); RunLogs(); PW_Log_Clear(); assert(RunTx() == 1);
    s_tick += 1001U; PW_LogRouter_Service(1U); PW_LogRouter_GetDiagnostics(&route_after);
    assert(route_after.subscribers == 0U && route_after.expired > route_before.expired);
    DropStaleCan(); assert(PwLogStore_Used() == 0U);

    /* A snapshot transfers references to DMA, not copies of history text. */
    PW_Log_SetSharedMirrorCallback(NULL); PW_Log_SetSharedCanMirrorCallback(NULL);
    assert(PW_Log_TestBurst(16U) == 16U); RunLogs(); assert(RunTx() == 1);
    UART_Async_GetDiagnostics(&before);
    assert(PW_Log_Dump() == 16U);
    PW_Log_Clear(); assert(PwLogStore_Used() == 16U);
    assert(RunTx() == 1 && PwLogStore_Used() == 0U);
    UART_Async_GetDiagnostics(&after);
    assert(after.shared_frames == before.shared_frames + 16U && after.copied_bytes == before.copied_bytes);

    /* Independent export owner survives Clear and overwrite, oldest-first. */
    assert(PW_Log_TestBurst(16U) == 16U); RunLogs(); assert(RunTx() == 1);
    PwLogRef exported[16];
    assert(PW_Log_HistorySnapshot(exported, 16U) == 16U);
    const uint32_t first_sequence = PwLogStore_View(exported[0])->sequence;
    PW_Log_Clear(); assert(PwLogStore_Used() == 16U);
    assert(PW_Log_TestBurst(16U) == 16U); RunLogs(); assert(RunTx() == 1);
    for (size_t i = 0; i < 16U; ++i) {
        assert(PwLogStore_View(exported[i])->sequence == first_sequence + i);
        assert(PwLogStore_Release(exported[i]));
    }
    PW_Log_Clear(); assert(PwLogStore_Used() == 0U);
    assert(PW_Log_HistorySnapshot(exported, 16U) == 0U);
    assert(PW_Log_HistorySnapshot(NULL, 16U) == 0U);

    /* Queue full preserves history, but releases the failed queue owner. */
    assert(PW_Log_TestBurst(100U) == 24U);
    PW_Log_GetDiagnostics(&diag);
    assert(diag.queued == 24U && diag.history_count == 16U && diag.dropped_full == 76U);
    RunLogs(); PW_Log_Clear(); assert(RunTx() == 1 && PwLogStore_Used() == 0U);

    /* Overwrite/Clear while dump waits for a full TX queue. */
    assert(PW_Log_TestBurst(16U) == 16U); RunLogs();
    assert(PW_Log_Dump() == 16U); /* 32 descriptors are now reserved */
    s_delay_hook = ClearDuringWait;
    assert(PW_Log_Dump() == 0U && s_delay_hook == NULL);
    assert(PwLogStore_Used() == 16U);
    assert(RunTx() == 1 && PwLogStore_Used() == 0U);

    /* Pool exhaustion is a bounded drop, never overwrite referenced content. */
    PwLogLease held[PW_LOG_STORE_CAPACITY];
    for (size_t i = 0U; i < PW_LOG_STORE_CAPACITY; ++i) assert(PwLogStore_Acquire(&held[i]));
    assert(PW_Log_TestBurst(1U) == 0U); PW_Log_GetDiagnostics(&diag); assert(diag.dropped_pool == 1U);
    for (size_t i = 0U; i < PW_LOG_STORE_CAPACITY; ++i) assert(PwLogStore_Cancel(&held[i]));
    mock_ipsr = 1U; assert(PW_Log_TestBurst(1U) == 0U); mock_ipsr = 0U;
    PW_Log_GetDiagnostics(&diag); assert(diag.dropped_isr == 1U);

    uint8_t token[] = {1U, 2U, 3U};
    assert(PW_Log_EnqueueTokenized(PW_LOG_RUNTIME_INFO, token, sizeof(token)) == 1U);
    memset(token, 0xff, sizeof(token)); RunLogs(); assert(RunTx() == 1);
    assert(strstr((const char *)s_tx_bytes, "$AQID") != NULL);
    PW_Log_Clear(); assert(PwLogStore_Used() == 0U);
    /* Real upstream Base64 buffer bounds and formatted CRLF/truncation. */
    uint8_t large_token[192]; memset(large_token, 0x55, sizeof(large_token));
    assert(!PW_Log_EnqueueTokenized(PW_LOG_RUNTIME_INFO, large_token, sizeof(large_token)));
    assert(PwLogStore_Used() == 0U);
    char long_body[300]; memset(long_body, 'x', sizeof(long_body) - 1U); long_body[299] = '\0';
    LogPrintf(PW_LOG_RUNTIME_WARN, "HOST", "%s", long_body);
    RunLogs(); assert(RunTx() == 1 && s_tx_length == PW_LOG_TEXT_BYTES - 1U);
    assert(s_tx_bytes[s_tx_length - 2U] == '\r' && s_tx_bytes[s_tx_length - 1U] == '\n');
    PW_Log_Clear(); assert(PwLogStore_Used() == 0U);
    assert(PW_Log_SetLevel(PW_LOG_RUNTIME_ERROR));
    LogPrintf(PW_LOG_RUNTIME_INFO, "HOST", "filtered");
    PW_Log_GetDiagnostics(&diag); assert(diag.filtered == 1U && diag.queued == 0U);
    assert(PW_Log_SetLevel(PW_LOG_RUNTIME_INFO));

    RouterPacket_t remote = {0}; remote.src = 3U; remote.type = PW_LOG_ROUTER_PACKET_TYPE;
    remote.length = 5U; memcpy(remote.payload, "hello", 5U);
    UART_Async_GetDiagnostics(&before); PW_LogRouter_HandleRemote(&remote);
    assert(RunTx() == 1 && s_tx_length == strlen("REMOTE LOG SRC=3 hello\r\n"));
    assert(!memcmp(s_tx_bytes, "REMOTE LOG SRC=3 hello\r\n", s_tx_length));
    UART_Async_GetDiagnostics(&after);
    assert(after.native_frames == before.native_frames + 1U && after.copied_bytes == before.copied_bytes);
    puts("PASS: shared history/pending/UART/Router/CAN owners, snapshot, full queues/pool, token lifetime");
}
static void SharedPinnedFault(void)
{
    assert(PW_Log_TestBurst(1U) == 1U); RunLogs();
    PW_Log_Clear(); assert(PwLogStore_Used() == 1U);
    s_tx_timeout = 1; s_abort_error = 1;
    assert(RunTx() == 2 && !UART_Async_IsReady());
    assert(PwLogStore_Used() == 1U && UartTxPool_ReservedBlocks() == 1U);
    assert(mock_dma1.CCR & DMA_CCR_EN);
    PW_Log_Clear(); assert(PwLogStore_Used() == 1U);
    assert(UART_Async_Init(&s_uart) == HAL_ERROR);
    puts("PASS: unsafe DMA abort pins shared log even after history clear, no re-init");
}
#if defined(PW_ALLOCATOR_HYBRID)
static void HybridSnapshotTests(void)
{
    PW_LogSnapshot snapshot = {0};
    PW_BufferDiagnostics stats = {0};
    assert(PW_Log_TestBurst(7U) == 7U); RunLogs(); assert(RunTx() == 1);
    assert(PW_LogSnapshot_Acquire(&snapshot));
    assert(snapshot.count == 7U && snapshot.index.capacity == 7U * sizeof(PwLogRef));
    assert(!PW_LogSnapshot_Acquire(&snapshot));
    PW_Buffer_GetDiagnostics(&stats);
    assert(stats.tag_bytes[PW_BUFFER_LOG_SNAPSHOT] == 28U);
    uint32_t sequence = PwLogStore_View(snapshot.refs[0])->sequence;
    PW_Log_Clear();
    assert(PwLogStore_Used() == 7U && PwLogStore_View(snapshot.refs[0])->sequence == sequence);
    PW_LogSnapshot_Release(&snapshot);
    PW_LogSnapshot_Release(&snapshot);
    assert(PwLogStore_Used() == 0U && PW_BufferTest_LiveAllocations() == 0U);

    assert(PW_Log_TestBurst(7U) == 7U); RunLogs(); assert(RunTx() == 1);
    PW_BufferTest_FailAllocation(1);
    assert(!PW_LogSnapshot_Acquire(&snapshot));
    assert(PW_Log_Dump() == 0U && UartTxPool_ReservedBlocks() == 0U);
    PW_BufferTest_FailAllocation(0);
    PW_Log_Clear();
    assert(PwLogStore_Used() == 0U && PW_BufferTest_LiveAllocations() == 0U);
    assert(PW_LogSnapshot_Acquire(&snapshot) && snapshot.count == 0U);
    PW_LogSnapshot_Release(&snapshot);
    puts("PASS: variable-size allocator log index, Clear pin, repeat release, OOM unwinds every record ref");
}
#endif
int main(void)
{
    TxTests(); ReferenceTests(); HistoryTests(); RxTests();
#if defined(PW_ALLOCATOR_HYBRID)
    HybridSnapshotTests();
#endif
    SharedPinnedFault();
    return 0;
}
