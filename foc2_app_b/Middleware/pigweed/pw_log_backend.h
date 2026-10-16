#ifndef PW_LOG_BACKEND_H
#define PW_LOG_BACKEND_H

#include <stddef.h>
#include <stdint.h>
#include "pw_log_store.h"

#ifdef __cplusplus
extern "C" {
#endif

enum
{
    PW_LOG_RUNTIME_DEBUG = 1,
    PW_LOG_RUNTIME_INFO = 2,
    PW_LOG_RUNTIME_WARN = 3,
    PW_LOG_RUNTIME_ERROR = 4,
    PW_LOG_RUNTIME_CRITICAL = 5,
    PW_LOG_RUNTIME_FATAL = 7
};

typedef struct
{
    uint32_t ready;
    uint32_t level;
    uint32_t queued;
    uint32_t capacity;
    uint32_t history_count;
    uint32_t sequence;
    uint32_t enqueued;
    uint32_t sent;
    uint32_t dropped_full;
    uint32_t dropped_uart;
    uint32_t dropped_isr;
    uint32_t filtered;
    uint32_t high_water;
    uint32_t tokenized;
    uint32_t token_binary_bytes;
    uint32_t token_base64_bytes;
    uint32_t pool_used;
    uint32_t dropped_pool;
} PW_LogDiagnostics_t;

typedef uint8_t (*PW_LogMirrorCallback_t)(uint8_t level,
                                          const char *text,
                                          size_t length);
/* Callback borrows a sealed record. Async mirrors retain before queueing and
 * release their owner on every complete/drop/failure path. */
typedef uint8_t (*PW_LogSharedMirrorCallback_t)(PwLogRef borrowed_ref);

int PW_Log_Init(void);
int PW_Log_SetLevel(int level);
void PW_Log_SetMirrorCallback(PW_LogMirrorCallback_t callback);
/* Independent best-effort CAN mirror; never replaces Router subscriptions. */
void PW_Log_SetCanMirrorCallback(PW_LogMirrorCallback_t callback);
void PW_Log_SetSharedMirrorCallback(PW_LogSharedMirrorCallback_t callback);
void PW_Log_SetSharedCanMirrorCallback(PW_LogSharedMirrorCallback_t callback);
const char *PW_Log_LevelName(int level);
void PW_Log_GetDiagnostics(PW_LogDiagnostics_t *diagnostics);
uint32_t PW_Log_Dump(void);
/* Task-only. Pins oldest-to-newest history refs; caller releases every owner.
 * Clear/overwrite does not invalidate the immutable snapshot. */
size_t PW_Log_HistorySnapshot(PwLogRef *out, size_t capacity);
void PW_Log_Clear(void);
uint32_t PW_Log_TestBurst(uint32_t count);
uint32_t PW_Log_EnqueueTokenized(uint32_t metadata,
                                 const uint8_t *buffer,
                                 size_t size);
uint32_t PW_Log_TokenizedTestBurst(uint32_t count);

#ifdef __cplusplus
}
#endif

#endif /* PW_LOG_BACKEND_H */
