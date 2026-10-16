#include "uart_rx_cursor.h"

void UartRxCursor_Init(UartRxCursor *cursor, uint32_t capacity)
{
    cursor->consumed = 0U;
    cursor->produced = 0U;
    cursor->total = 0U;
    cursor->dropped = 0U;
    cursor->gaps = 0U;
    cursor->capacity = capacity;
}

uint32_t UartRxCursor_Position(uint32_t half_events, uint32_t offset,
                             uint32_t capacity)
{
    uint32_t phase = (offset >= capacity / 2U) ? 1U : 0U;
    /* NDTR may cross a boundary just before its IRQ callback. Infer that one
     * pending half event; never infer more than one. IRQs must be serviced
     * within one half-buffer period (UART/DMA has no infinite overrun history). */
    if ((half_events & 1U) != phase) ++half_events;
    return (half_events / 2U) * capacity + offset;
}

size_t UartRxCursor_Update(UartRxCursor *cursor, uint32_t produced)
{
    uint32_t available;
    cursor->total += produced - cursor->produced;
    cursor->produced = produced;
    available = produced - cursor->consumed;
    if (available >= cursor->capacity) {
        /* At capacity the next hardware write can overwrite the first byte.
         * Discard the whole unsafe window; parser must resync at a delimiter. */
        cursor->dropped += available;
        cursor->consumed = produced;
        ++cursor->gaps;
        return 0U;
    }
    return available;
}

void UartRxCursor_Gap(UartRxCursor *cursor)
{
    cursor->dropped += cursor->produced - cursor->consumed;
    cursor->consumed = cursor->produced;
    ++cursor->gaps;
}
