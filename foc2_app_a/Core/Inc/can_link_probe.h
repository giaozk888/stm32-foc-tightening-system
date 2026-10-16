#ifndef CAN_LINK_PROBE_H
#define CAN_LINK_PROBE_H

#include "stm32g4xx_hal.h"

/* Standalone bring-up image: never returns to the motor application. */
__attribute__((noreturn)) void CAN_LinkProbe_RunForever(UART_HandleTypeDef *uart);

#endif
