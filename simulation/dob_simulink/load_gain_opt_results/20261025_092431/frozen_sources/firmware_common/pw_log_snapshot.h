#ifndef PW_LOG_SNAPSHOT_H
#define PW_LOG_SNAPSHOT_H
#include "pw_log_backend.h"
#if defined(PW_ALLOCATOR_HYBRID)
#include "pw_managed_buffer.h"
#endif
#ifdef __cplusplus
extern "C" {
#endif

/* Snapshot owns only record references, not copies of their text. Init to zero,
 * acquire once, release on completion/error/cancel. No heap under log lock.
 * Hybrid mode requires normal task context at priority 0..2 for both calls. */
typedef struct {
    PwLogRef *refs;
    size_t count;
#if defined(PW_ALLOCATOR_HYBRID)
    PW_BufferLease index;
#else
    PwLogRef fixed[16];
#endif
} PW_LogSnapshot;
int PW_LogSnapshot_Acquire(PW_LogSnapshot *snapshot);
void PW_LogSnapshot_Release(PW_LogSnapshot *snapshot);
#ifdef __cplusplus
}
#endif
#endif
