#ifndef UART_RX_CURSOR_H
#define UART_RX_CURSOR_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint32_t consumed;
    uint32_t produced;
    uint32_t total;
    uint32_t dropped;
    uint32_t gaps;
    uint32_t capacity;
} UartRxCursor;

/* Single-consumer logical cursor. ISR half-count updates are handled by the
 * platform adapter. Unsigned absolute positions intentionally wrap at 2^32. */
void UartRxCursor_Init(UartRxCursor *cursor, uint32_t capacity);
uint32_t UartRxCursor_Position(uint32_t half_events, uint32_t offset,
                             uint32_t capacity);
size_t UartRxCursor_Update(UartRxCursor *cursor, uint32_t produced);
void UartRxCursor_Gap(UartRxCursor *cursor);
#ifdef __cplusplus
}
#endif
#endif
