#ifndef PW_CAN_LOG_H
#define PW_CAN_LOG_H
#include <stdint.h>
uint8_t PW_CanLog_Init(void);
/* MonitorTask only, after telemetry had time to drain. No HAL calls in producer. */
void PW_CanLog_Service(uint32_t now_ms);
#endif
