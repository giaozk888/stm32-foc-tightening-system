#ifndef STM32_ESP_STACK_DIAG_FREERTOS_CONFIG_H
#define STM32_ESP_STACK_DIAG_FREERTOS_CONFIG_H

/* Reuse the project's API/priority policy, but match this RAM-only harness's
 * reset HSI16 clock rather than the production application's 170 MHz PLL. */
#include "../../foc2_app_a/Core/Inc/FreeRTOSConfig.h"
#undef configCPU_CLOCK_HZ
#define configCPU_CLOCK_HZ 16000000UL
#undef configTOTAL_HEAP_SIZE
#define configTOTAL_HEAP_SIZE (20U * 1024U)

#endif
