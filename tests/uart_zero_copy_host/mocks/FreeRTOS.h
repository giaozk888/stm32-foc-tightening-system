#ifndef MOCK_FREERTOS_H
#define MOCK_FREERTOS_H
#include <stdint.h>
typedef int BaseType_t;
typedef unsigned int UBaseType_t;
typedef uint32_t TickType_t;
typedef uint32_t StackType_t;
typedef struct { unsigned int unused; } StaticTask_t;
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define portMAX_DELAY UINT32_MAX
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))
#define portYIELD_FROM_ISR(woken) ((void)(woken))
#if defined(PW_TRANSFER_HOST)
#ifdef __cplusplus
extern "C" {
#endif
void RPC_TestLock(void);
void RPC_TestUnlock(void);
#ifdef __cplusplus
}
#endif
#define taskENTER_CRITICAL() RPC_TestLock()
#define taskEXIT_CRITICAL() RPC_TestUnlock()
#else
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
#endif
#define portTICK_PERIOD_MS 1U
#endif
