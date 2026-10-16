#ifndef MOCK_TASK_H
#define MOCK_TASK_H
#include "FreeRTOS.h"
typedef void *TaskHandle_t;
typedef void (*TaskFunction_t)(void *);
BaseType_t xTaskCreate(TaskFunction_t function, const char *name, uint32_t stack,
                       void *argument, uint32_t priority, TaskHandle_t *handle);
TickType_t xTaskGetTickCount(void);
void vTaskDelay(TickType_t ticks);
TaskHandle_t xTaskCreateStatic(TaskFunction_t function, const char *name,
                              uint32_t stack, void *argument, uint32_t priority,
                              StackType_t *buffer, StaticTask_t *control);
#endif
