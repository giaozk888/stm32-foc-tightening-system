#ifndef ESP_LINK_H
#define ESP_LINK_H

#include <stdint.h>

#include "router.h"

/* Stage 10.2: read-only discovery over USART1 PA9/PA10.
 * No ESP ingress command is allowed to reach motor control. */
uint8_t EspLink_Init(void);
void EspLink_Deinit(void);
void EspLink_Task(void *argument);
uint8_t EspLink_RouterTx(const RouterPacket_t *packet);

#endif
