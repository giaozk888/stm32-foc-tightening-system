#ifndef FOC_PREEMPT_MOCK_UART_H
#define FOC_PREEMPT_MOCK_UART_H
#include <stddef.h>
#include <stdint.h>
size_t UART_Async_Printf(size_t size,uint32_t timeout,const char *format,...);
#endif
