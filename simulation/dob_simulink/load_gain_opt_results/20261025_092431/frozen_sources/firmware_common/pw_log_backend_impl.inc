/* Shared A/B platform implementation. Compiled by each slot's backend.c. */
#include "pw_log_backend.h"
#include "pw_log_snapshot.h"
#include "uart_tx_reference.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include "pw_tokenizer/base64.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdatomic.h>

/* Keep the platform library independent of HAL/main.h. */
static uint32_t InInterrupt(void)
{
#ifdef PW_LOG_HOST_TEST
    extern uint32_t PW_Log_TestInterruptState(void);
    return PW_Log_TestInterruptState();
#else
    uint32_t ipsr;
    __asm volatile("mrs %0, ipsr" : "=r"(ipsr));
    return ipsr;
#endif
}

#define PW_LOG_PENDING_CAPACITY 24U
#define PW_LOG_HISTORY_CAPACITY 16U
#define PW_LOG_TASK_STACK_WORDS 384U
#define PW_LOG_TASK_PRIORITY 1U
static StaticQueue_t s_queue_control;
static uint8_t s_queue_storage[PW_LOG_PENDING_CAPACITY * sizeof(PwLogRef)];
static QueueHandle_t s_queue;
static StaticTask_t s_task_control;
static StackType_t s_task_stack[PW_LOG_TASK_STACK_WORDS];
static TaskHandle_t s_task;
static PwLogRef s_history[PW_LOG_HISTORY_CAPACITY];
static uint32_t s_history_head, s_history_count;
static volatile uint32_t s_ready, s_level = PW_LOG_RUNTIME_INFO, s_sequence;
static uint32_t s_enqueued, s_sent, s_dropped_full, s_dropped_uart;
static atomic_uint s_dropped_isr;
static uint32_t s_filtered, s_high_water, s_tokenized, s_token_binary_bytes;
static uint32_t s_token_base64_bytes, s_dropped_pool;
static PW_LogMirrorCallback_t s_mirror_callback, s_can_mirror_callback;
static PW_LogSharedMirrorCallback_t s_shared_mirror, s_shared_can_mirror;

const char *PW_Log_LevelName(int level)
{
    switch (level) {
        case PW_LOG_RUNTIME_DEBUG: return "DEBUG";
        case PW_LOG_RUNTIME_INFO: return "INFO";
        case PW_LOG_RUNTIME_WARN: return "WARN";
        case PW_LOG_RUNTIME_ERROR: return "ERROR";
        case PW_LOG_RUNTIME_CRITICAL: return "CRITICAL";
        case PW_LOG_RUNTIME_FATAL: return "FATAL";
        default: return "UNKNOWN";
    }
}
static int LevelValid(int level)
{
    return (level >= PW_LOG_RUNTIME_DEBUG && level <= PW_LOG_RUNTIME_CRITICAL) ||
           level == PW_LOG_RUNTIME_FATAL;
}
static void Increment(uint32_t *counter)
{
    taskENTER_CRITICAL(); ++*counter; taskEXIT_CRITICAL();
}
static int BeginRecord(int level, PwLogLease *lease)
{
    if (!s_ready) return 0;
    if (InInterrupt() != 0U) {
        atomic_fetch_add_explicit(&s_dropped_isr, 1U, memory_order_relaxed);
        return 0;
    }
    if (level < (int)s_level) { Increment(&s_filtered); return 0; }
    if (!PwLogStore_Acquire(lease)) { Increment(&s_dropped_pool); return 0; }
    taskENTER_CRITICAL(); lease->record->sequence = ++s_sequence; taskEXIT_CRITICAL();
    lease->record->tick = (uint32_t)xTaskGetTickCount();
    lease->record->level = (uint8_t)level;
    lease->record->length = 0U;
    return 1;
}
static void RecordHistory(PwLogRef ref)
{
    PwLogRef replaced;
    if (!PwLogStore_Retain(ref)) return;
    taskENTER_CRITICAL();
    replaced = s_history[s_history_head];
    s_history[s_history_head] = ref;
    s_history_head = (s_history_head + 1U) % PW_LOG_HISTORY_CAPACITY;
    if (s_history_count < PW_LOG_HISTORY_CAPACITY) ++s_history_count;
    taskEXIT_CRITICAL();
    if (replaced != 0U) (void)PwLogStore_Release(replaced);
}
static uint8_t FinishRecord(PwLogLease *lease, size_t token_bytes, size_t encoded_bytes)
{
    PwLogRef ref;
    UBaseType_t queued;
    if (!PwLogStore_Seal(lease, &ref)) {
        (void)PwLogStore_Cancel(lease);
        return 0U;
    }
    RecordHistory(ref);
    if (xQueueSend(s_queue, &ref, 0U) != pdPASS) {
        (void)PwLogStore_Release(ref);
        Increment(&s_dropped_full);
        return 0U;
    }
    /* Queue owns the original reference; no payload access after publication. */
    queued = uxQueueMessagesWaiting(s_queue);
    taskENTER_CRITICAL();
    ++s_enqueued;
    if (token_bytes != 0U) {
        ++s_tokenized;
        s_token_binary_bytes += (uint32_t)token_bytes;
        s_token_base64_bytes += (uint32_t)encoded_bytes;
    }
    if ((uint32_t)queued > s_high_water) s_high_water = (uint32_t)queued;
    taskEXIT_CRITICAL();
    return 1U;
}
static uint8_t EnqueueFormatted(int level, const char *module, const char *format, va_list args)
{
    PwLogLease lease = {0};
    PwLogRecord *record;
    int prefix, body;
    size_t length;
    if (format == NULL || !BeginRecord(level, &lease)) return 0U;
    record = lease.record;
    if (module == NULL || *module == '\0') module = "APP";
    prefix = snprintf(record->text, PW_LOG_TEXT_BYTES, "[PW][%lu][%lums][%s][%s] ",
                      (unsigned long)record->sequence, (unsigned long)record->tick,
                      PW_Log_LevelName(level), module);
    if (prefix < 0 || (size_t)prefix >= PW_LOG_TEXT_BYTES - 2U) {
        (void)PwLogStore_Cancel(&lease); return 0U;
    }
    /* Format body directly into final storage, without a temporary body[]. */
    body = vsnprintf(record->text + prefix, PW_LOG_TEXT_BYTES - (size_t)prefix, format, args);
    if (body < 0) { (void)PwLogStore_Cancel(&lease); return 0U; }
    length = (size_t)prefix + (size_t)body;
    if (length > PW_LOG_TEXT_BYTES - 3U) length = PW_LOG_TEXT_BYTES - 3U;
    record->text[length++] = '\r'; record->text[length++] = '\n';
    record->text[length] = '\0'; record->length = (uint16_t)length;
    return FinishRecord(&lease, 0U, 0U);
}
static uint8_t EnqueuePrintf(int level, const char *module, const char *format, ...)
{
    uint8_t accepted;
    va_list args;
    va_start(args, format); accepted = EnqueueFormatted(level, module, format, args); va_end(args);
    return accepted;
}
static void ReleaseUartReference(uint32_t ref) { (void)PwLogStore_Release(ref); }
static int SubmitUart(PwLogRef ref, uint32_t timeout_ms)
{
    const PwLogRecord *record = PwLogStore_View(ref);
    if (record == NULL || !PwLogStore_Retain(ref)) return 0;
    if (UART_Async_SubmitReference((const uint8_t *)record->text, record->length,
            ReleaseUartReference, ref, timeout_ms) != record->length) {
        (void)PwLogStore_Release(ref); return 0;
    }
    return 1;
}
static void PW_Log_Task(void *argument)
{
    PwLogRef ref;
    (void)argument;
    for (;;) {
        if (xQueueReceive(s_queue, &ref, portMAX_DELAY) == pdTRUE) {
            const PwLogRecord *record = PwLogStore_View(ref);
            PW_LogSharedMirrorCallback_t shared, can_shared;
            PW_LogMirrorCallback_t legacy, can_legacy;
            if (SubmitUart(ref, 0U)) Increment(&s_sent); else Increment(&s_dropped_uart);
            taskENTER_CRITICAL();
            shared = s_shared_mirror; can_shared = s_shared_can_mirror;
            legacy = s_mirror_callback; can_legacy = s_can_mirror_callback;
            taskEXIT_CRITICAL();
            /* Callbacks borrow this owner; async mirrors retain their own ref. */
            if (record != NULL) {
                if (shared != NULL) (void)shared(ref);
                else if (legacy != NULL) (void)legacy(record->level, record->text, record->length);
                if (can_shared != NULL) (void)can_shared(ref);
                else if (can_legacy != NULL) (void)can_legacy(record->level, record->text, record->length);
            }
            (void)PwLogStore_Release(ref);
        }
    }
}
int PW_Log_Init(void)
{
    if (s_ready) return 1;
    if (s_task != NULL || !UART_Async_IsReady()) return 0;
    PwLogStore_Init(); /* startup only; Clear never resets the pool */
    s_queue = xQueueCreateStatic(PW_LOG_PENDING_CAPACITY, sizeof(PwLogRef),
                                 s_queue_storage, &s_queue_control);
    if (s_queue == NULL) return 0;
    s_task = xTaskCreateStatic(PW_Log_Task, "PwLog", PW_LOG_TASK_STACK_WORDS, NULL,
                               PW_LOG_TASK_PRIORITY, s_task_stack, &s_task_control);
    if (s_task == NULL) return 0;
    s_ready = 1U;
    return 1;
}
int PW_Log_SetLevel(int level)
{
    if (!LevelValid(level)) return 0;
    taskENTER_CRITICAL(); s_level = (uint32_t)level; taskEXIT_CRITICAL(); return 1;
}
void PW_Log_SetMirrorCallback(PW_LogMirrorCallback_t callback)
{
    taskENTER_CRITICAL(); s_mirror_callback = callback; s_shared_mirror = NULL; taskEXIT_CRITICAL();
}
void PW_Log_SetCanMirrorCallback(PW_LogMirrorCallback_t callback)
{
    taskENTER_CRITICAL(); s_can_mirror_callback = callback; s_shared_can_mirror = NULL; taskEXIT_CRITICAL();
}
void PW_Log_SetSharedMirrorCallback(PW_LogSharedMirrorCallback_t callback)
{
    taskENTER_CRITICAL(); s_shared_mirror = callback; s_mirror_callback = NULL; taskEXIT_CRITICAL();
}
void PW_Log_SetSharedCanMirrorCallback(PW_LogSharedMirrorCallback_t callback)
{
    taskENTER_CRITICAL(); s_shared_can_mirror = callback; s_can_mirror_callback = NULL; taskEXIT_CRITICAL();
}
void PW_Log_GetDiagnostics(PW_LogDiagnostics_t *out)
{
    if (out == NULL) return;
    taskENTER_CRITICAL();
    out->ready = s_ready; out->level = s_level; out->capacity = PW_LOG_PENDING_CAPACITY;
    out->history_count = s_history_count; out->sequence = s_sequence; out->enqueued = s_enqueued;
    out->sent = s_sent; out->dropped_full = s_dropped_full; out->dropped_uart = s_dropped_uart;
    out->dropped_isr = atomic_load_explicit(&s_dropped_isr, memory_order_relaxed);
    out->filtered = s_filtered; out->high_water = s_high_water;
    out->tokenized = s_tokenized; out->token_binary_bytes = s_token_binary_bytes;
    out->token_base64_bytes = s_token_base64_bytes; out->dropped_pool = s_dropped_pool;
    taskEXIT_CRITICAL();
    out->queued = s_queue != NULL ? (uint32_t)uxQueueMessagesWaiting(s_queue) : 0U;
    out->pool_used = (uint32_t)PwLogStore_Used();
}
size_t PW_Log_HistorySnapshot(PwLogRef *out, size_t capacity)
{
    size_t count = 0U;
    if (!out || !capacity || !s_ready || InInterrupt() != 0U) return 0U;
    taskENTER_CRITICAL();
    uint32_t start = (s_history_head + PW_LOG_HISTORY_CAPACITY - s_history_count) % PW_LOG_HISTORY_CAPACITY;
    for (uint32_t i = 0U; i < s_history_count && count < capacity; ++i) {
        PwLogRef ref = s_history[(start + i) % PW_LOG_HISTORY_CAPACITY];
        if (PwLogStore_Retain(ref)) out[count++] = ref;
    }
    taskEXIT_CRITICAL();
    return count;
}
uint32_t PW_Log_Dump(void)
{
    PW_LogSnapshot snapshot = {0};
    uint32_t sent = 0U;
    if (!PW_LogSnapshot_Acquire(&snapshot)) return 0U;
    /* Pinned snapshot, no payload copy. Concurrent Clear/overwrite cannot change
     * it. UART submission/wait is outside the short critical section. */
    for (size_t i = 0U; i < snapshot.count; ++i) {
        if (SubmitUart(snapshot.refs[i], 100U)) ++sent;
    }
    PW_LogSnapshot_Release(&snapshot);
    return sent;
}
void PW_Log_Clear(void)
{
    PwLogRef removed[PW_LOG_HISTORY_CAPACITY];
    if (InInterrupt() != 0U) return;
    taskENTER_CRITICAL();
    for (uint32_t i = 0U; i < PW_LOG_HISTORY_CAPACITY; ++i) {
        removed[i] = s_history[i]; s_history[i] = 0U;
    }
    s_history_head = 0U; s_history_count = 0U;
    s_enqueued = 0U; s_sent = 0U; s_dropped_full = 0U; s_dropped_uart = 0U;
    atomic_store_explicit(&s_dropped_isr, 0U, memory_order_relaxed);
    s_filtered = 0U; s_high_water = 0U; s_tokenized = 0U;
    s_token_binary_bytes = 0U; s_token_base64_bytes = 0U; s_dropped_pool = 0U;
    taskEXIT_CRITICAL();
    for (uint32_t i = 0U; i < PW_LOG_HISTORY_CAPACITY; ++i)
        if (removed[i] != 0U) (void)PwLogStore_Release(removed[i]);
    /* Pending queues/mirrors/DMA still own their independent references. */
}
uint32_t PW_Log_TestBurst(uint32_t count)
{
    uint32_t accepted = 0U;
    if (count > 1000U) count = 1000U;
    for (uint32_t i = 0U; i < count; ++i)
        accepted += EnqueuePrintf(PW_LOG_RUNTIME_INFO, "LOGTEST", "burst index=%lu", (unsigned long)i);
    return accepted;
}
uint32_t PW_Log_EnqueueTokenized(uint32_t metadata, const uint8_t *buffer, size_t size)
{
    PwLogLease lease = {0};
    PwLogRecord *record;
    size_t encoded;
    int prefix, level = (int)(metadata & 0x7U);
    if (buffer == NULL || size == 0U || !BeginRecord(level, &lease)) return 0U;
    record = lease.record;
    prefix = snprintf(record->text, PW_LOG_TEXT_BYTES, "[PWT][%lu][%lums][%s][M=%08lX][B=%lu] ",
                      (unsigned long)record->sequence, (unsigned long)record->tick,
                      PW_Log_LevelName(level), (unsigned long)metadata, (unsigned long)size);
    if (prefix < 0 || (size_t)prefix >= PW_LOG_TEXT_BYTES - 3U) {
        (void)PwLogStore_Cancel(&lease); return 0U;
    }
    /* Transient upstream token bytes are encoded synchronously into final
     * shared storage, without encoded[] or a whole-record staging copy. */
    encoded = pw_tokenizer_PrefixedBase64Encode(buffer, size, record->text + prefix,
                                                PW_LOG_TEXT_BYTES - (size_t)prefix - 2U);
    if (encoded == 0U) { (void)PwLogStore_Cancel(&lease); return 0U; }
    size_t length = (size_t)prefix + encoded;
    record->text[length++] = '\r'; record->text[length++] = '\n'; record->text[length] = '\0';
    record->length = (uint16_t)length;
    return FinishRecord(&lease, size, encoded);
}
void pw_log_string_HandleMessageVaList(int level, unsigned int flags, const char *module,
                                       const char *file, int line, const char *message, va_list args)
{
    (void)flags; (void)file; (void)line;
    (void)EnqueueFormatted(level, module, message, args);
}
