#ifndef FOC_ADC_TEST_TASK_H
#define FOC_ADC_TEST_TASK_H
#include "FreeRTOS.h"
TaskHandle_t xTaskCreateStatic(void (*entry)(void *), const char *name,
    uint32_t depth, void *argument, UBaseType_t priority,
    StackType_t *stack, StaticTask_t *tcb);
UBaseType_t uxTaskGetStackHighWaterMark(TaskHandle_t task);
void vTaskDelay(TickType_t ticks);
#endif
