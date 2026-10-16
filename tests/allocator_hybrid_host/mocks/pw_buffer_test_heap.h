#ifndef PW_BUFFER_TEST_HEAP_H
#define PW_BUFFER_TEST_HEAP_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
int PW_BufferTest_Allowed(void);
void PW_BufferTest_SetContext(int isr, int scheduler_running, unsigned priority);
void PW_BufferTest_SetMasked(int masked);
void PW_BufferTest_Suspend(void);
void PW_BufferTest_Resume(void);
size_t PW_BufferTest_FreeHeap(void);
void PW_BufferTest_SetFreeHeap(size_t free_bytes);
void PW_BufferTest_FailAllocation(int fail);
size_t PW_BufferTest_LiveAllocations(void);
#ifdef __cplusplus
}
#endif
#endif
