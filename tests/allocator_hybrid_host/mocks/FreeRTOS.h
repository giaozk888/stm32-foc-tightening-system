#ifndef PW_BUFFER_MOCK_FREERTOS_H
#define PW_BUFFER_MOCK_FREERTOS_H
#include <stddef.h>
#define portBYTE_ALIGNMENT 8U
#ifdef __cplusplus
extern "C" {
#endif
void *pvPortMalloc(size_t bytes);
void vPortFree(void *pointer);
#ifdef __cplusplus
}
#endif
#endif
