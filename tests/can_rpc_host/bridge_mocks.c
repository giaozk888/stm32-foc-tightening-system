#include "pw_can_rpc.h"
#include "rpc_readonly.h"
#include "queue.h"
#include "pw_log_backend.h"
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "test_assert.h"
unsigned rpc_test_flash_calls, rpc_test_ascii_calls, rpc_test_snapshot_calls;
unsigned rpc_test_send_allowed = 1U;
unsigned rpc_test_now;
TickType_t xTaskGetTickCount(void) { return rpc_test_now; }
static PwLogRef history[16];
static size_t history_count;
void RPC_TestClearHistory(void) {
    taskENTER_CRITICAL();
    for (size_t i=0; i<history_count; ++i) (void)PwLogStore_Release(history[i]);
    history_count=0;
    taskEXIT_CRITICAL();
}
void RPC_TestSetHistory(const char *text, size_t length) {
    taskENTER_CRITICAL();
    RPC_TestClearHistory();
    while (length) {
        PwLogLease lease={0}; assert(history_count < 16 && PwLogStore_Acquire(&lease));
        const size_t take=length < 191 ? length : 191;
        memcpy(lease.record->text,text,take); lease.record->text[take]='\0'; lease.record->length=(uint16_t)take;
        assert(PwLogStore_Seal(&lease,&history[history_count++])); text+=take; length-=take;
    }
    taskEXIT_CRITICAL();
}
size_t PW_Log_HistorySnapshot(PwLogRef *out, size_t capacity) {
    taskENTER_CRITICAL();
    size_t count=history_count < capacity ? history_count : capacity;
    for (size_t i=0; i<count; ++i) { assert(PwLogStore_Retain(history[i])); out[i]=history[i]; }
    taskEXIT_CRITICAL(); return count;
}
void PW_Log_GetDiagnostics(PW_LogDiagnostics_t *out) { memset(out,0,sizeof(*out)); out->ready=1; }
extern void RPC_TestOnCanFrame(const uint8_t data[8]);
QueueHandle_t xQueueCreateStatic(UBaseType_t depth, UBaseType_t size, uint8_t *storage, StaticQueue_t *q) {
    q->depth = depth; q->item_size = size; q->storage = storage; q->head = q->count = 0U; return q;
}
BaseType_t xQueueSend(QueueHandle_t q, const void *item, TickType_t ticks) {
    (void)ticks; taskENTER_CRITICAL(); if (q->count == q->depth) { taskEXIT_CRITICAL(); return pdFALSE; }
    memcpy(q->storage + ((q->head + q->count) % q->depth) * q->item_size, item, q->item_size);
    ++q->count; taskEXIT_CRITICAL(); return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t q, void *item, TickType_t ticks) {
    (void)ticks; taskENTER_CRITICAL(); if (!q->count) { taskEXIT_CRITICAL(); return pdFALSE; }
    memcpy(item, q->storage + q->head * q->item_size, q->item_size);
    q->head = (q->head + 1U) % q->depth; --q->count; taskEXIT_CRITICAL(); return pdTRUE;
}
void CAN_StatusTx_GetHealth(CAN_StatusTx_Health *out) {
    memset(out, 0, sizeof(*out)); out->ready = 1U;
}
uint8_t CAN_StatusTx_TryRpcFrame(uint32_t id, const uint8_t data[8]) {
    assert(id == CAN_RPC_REPLY_ID);
    if (!rpc_test_send_allowed) return 0U;
    RPC_TestOnCanFrame(data); return 1U;
}
uint8_t PW_Rpc_ProtocolSend(const char *line) { (void)line; ++rpc_test_ascii_calls; return 1U; }
uint8_t PW_TransferFlash_IsActive(void) { ++rpc_test_flash_calls; return 1U; }
uint32_t PW_TransferFlash_ExpectedOffset(void) { ++rpc_test_flash_calls; return 0U; }
uint32_t PW_TransferFlash_ImageSize(void) { ++rpc_test_flash_calls; return 100U; }
uint8_t PW_TransferFlash_Write(uint32_t offset, const uint8_t *data, uint32_t length) {
    (void)offset; (void)data; (void)length; ++rpc_test_flash_calls; return 1U;
}
size_t PW_Rpc_ReadOnlySnapshot(uint32_t kind, uint8_t *out, size_t capacity) {
    ++rpc_test_snapshot_calls;
    const size_t count = kind == RPC_READONLY_SNAPSHOT_STATUS ? RPC_READONLY_STATUS_WORDS :
        kind == RPC_READONLY_SNAPSHOT_PARAMS ? RPC_READONLY_PARAMS_WORDS : RPC_READONLY_DIAG_WORDS;
    assert(capacity >= count * 4U);
    for (size_t i = 0; i < count; ++i) {
        const uint32_t value = i == 0 ? RPC_READONLY_VERSION : (kind == RPC_READONLY_SNAPSHOT_STATUS && i == 7 ? 0U : (uint32_t)i);
        for (unsigned byte = 0; byte < 4; ++byte) out[i*4U+byte] = (uint8_t)(value >> (byte*8U));
    }
    return count * 4U;
}
void pw_log_string_HandleMessageVaList(int level, unsigned int flags, const char *module,
    const char *file, int line, const char *message, va_list args) {
    (void)level; (void)flags; (void)module; (void)file; (void)line;
    vfprintf(stderr, message, args); fputc('\n', stderr);
}
