#ifndef MOCK_QUEUE_H
#define MOCK_QUEUE_H
#include "FreeRTOS.h"
#include <stddef.h>
typedef struct {
    size_t depth, item_size, head, count;
    uint8_t *storage;
} StaticQueue_t;
typedef StaticQueue_t *QueueHandle_t;
QueueHandle_t xQueueCreate(UBaseType_t depth, UBaseType_t item_size);
QueueHandle_t xQueueCreateStatic(UBaseType_t depth, UBaseType_t item_size,
                                 uint8_t *storage, StaticQueue_t *control);
BaseType_t xQueueSend(QueueHandle_t queue, const void *item, TickType_t ticks);
BaseType_t xQueueReceive(QueueHandle_t queue, void *item, TickType_t ticks);
UBaseType_t uxQueueMessagesWaiting(QueueHandle_t queue);
#endif
