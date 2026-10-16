/* Reuse only the public Router interface, not the STM32 FreeRTOSConfig/HAL
 * include directory. ESP-IDF owns this target's FreeRTOS configuration. */
#include "../../foc2_app_a/Core/Inc/router.h"
