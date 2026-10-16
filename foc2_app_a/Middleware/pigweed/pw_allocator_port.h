#ifndef PW_ALLOCATOR_PORT_H
#define PW_ALLOCATOR_PORT_H

#include <stdint.h>
#include "pw_managed_buffer.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
    uint32_t free_bytes;
    uint32_t minimum_ever_free_bytes;
    uint32_t last_test_before_bytes;
    uint32_t last_test_low_bytes;
    uint32_t last_test_after_bytes;
    uint32_t last_test_allocations;
    uint32_t last_test_passed;
    uint32_t hybrid_enabled;
    PW_BufferDiagnostics managed;
} PW_AllocatorDiagnostics_t;

/*
 * Runs a bounded allocation/deallocation test from task context.
 * This API must never be called from an ISR or the 20 kHz FOC path.
 */
int PW_Allocator_RunSelfTest(void);
void PW_Allocator_GetDiagnostics(PW_AllocatorDiagnostics_t *diagnostics);

#ifdef __cplusplus
}
#endif

#endif /* PW_ALLOCATOR_PORT_H */
