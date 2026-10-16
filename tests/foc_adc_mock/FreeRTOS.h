#ifndef FOC_ADC_TEST_FREERTOS_H
#define FOC_ADC_TEST_FREERTOS_H
#include <stddef.h>
#include <stdint.h>
typedef uint32_t StackType_t;
typedef uint32_t TickType_t;
typedef unsigned UBaseType_t;
typedef struct { uint32_t placeholder; } StaticTask_t;
typedef void *TaskHandle_t;
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))
#endif
