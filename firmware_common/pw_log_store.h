#ifndef PW_LOG_STORE_H
#define PW_LOG_STORE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define PW_LOG_STORE_CAPACITY 64U
#define PW_LOG_TEXT_BYTES 192U
typedef uint32_t PwLogRef; /* generation + slot; zero is invalid */
typedef struct {
    uint32_t sequence;
    uint32_t tick;
    uint16_t length;
    uint8_t level;
    char text[PW_LOG_TEXT_BYTES];
} PwLogRecord;
typedef struct { PwLogRef ref; PwLogRecord *record; } PwLogLease;

/* Init is startup/quiescent only, never a clear/reset operation. A lease has
 * one writer. Seal transfers its one owned reference to out; all subsequent
 * readers need their own retained reference. View does not acquire ownership.
 * Do not modify sealed data or use a handle after Release. Generation wraps;
 * stale-handle checks are diagnostics, not an authorization mechanism. */
void PwLogStore_Init(void);
int PwLogStore_Acquire(PwLogLease *out);
int PwLogStore_Seal(PwLogLease *lease, PwLogRef *out);
int PwLogStore_Cancel(PwLogLease *lease);
int PwLogStore_Retain(PwLogRef ref);
int PwLogStore_Release(PwLogRef ref);
const PwLogRecord *PwLogStore_View(PwLogRef owned_ref);
size_t PwLogStore_Used(void);

#ifdef __cplusplus
}
#endif
#endif
