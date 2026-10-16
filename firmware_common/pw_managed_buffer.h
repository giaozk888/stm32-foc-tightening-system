#ifndef PW_MANAGED_BUFFER_H
#define PW_MANAGED_BUFFER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* A bounded adapter over the real Pigweed FreeRtosAllocator/heap_4. This does
 * not install global new/malloc hooks. Task priorities 0..2 only, scheduler
 * running, never ISR/FOC/critical section/interrupt-masked context.
 * Heap operations use a priority-inheritance mutex.
 * Quotas exclude heap_4 headers; the free-heap floor includes that overhead. */
#define PW_BUFFER_MAX_BYTES 2048U
#define PW_BUFFER_TOTAL_BYTES 4096U
#define PW_BUFFER_HEAP_RESERVE 4096U
#define PW_BUFFER_SLOTS 16U

typedef enum {
    PW_BUFFER_UART = 0,
    PW_BUFFER_LOG_SNAPSHOT = 1,
    PW_BUFFER_TEMP = 2,
    PW_BUFFER_TAG_COUNT = 3
} PW_BufferTag;

typedef struct {
    uint8_t *data;
    size_t capacity;
    uint32_t token;
} PW_BufferLease;

typedef uint32_t PW_BufferRef;
typedef struct {
    uint32_t live_bytes, peak_bytes, live_objects;
    uint32_t allocations, frees, allocation_failures, context_rejections;
    uint32_t invalid_owners;
    uint32_t tag_bytes[PW_BUFFER_TAG_COUNT];
} PW_BufferDiagnostics;

/* Single-owner writer. Success overwrites out; failure leaves out unchanged.
 * Never overwrite a live lease, copy its ownership, or access it after cancel
 * or seal. A caller-owned temporary object can just allocate/use/cancel.
 * Seal makes data immutable and transfers exactly one shared reference. */
int PW_Buffer_Allocate(size_t bytes, PW_BufferTag tag, PW_BufferLease *out);
int PW_Buffer_ContextAllowed(void);
int PW_Buffer_Cancel(PW_BufferLease *lease);
int PW_Buffer_Seal(PW_BufferLease *lease, PW_BufferRef *out);
int PW_Buffer_Retain(PW_BufferRef ref);
int PW_Buffer_Release(PW_BufferRef ref);
/* Caller must already own a reference for the entire lifetime of the view. */
const uint8_t *PW_Buffer_View(PW_BufferRef ref, size_t *capacity);
void PW_Buffer_GetDiagnostics(PW_BufferDiagnostics *out);

#ifdef __cplusplus
}
#endif
#endif
