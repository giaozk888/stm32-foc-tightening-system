#ifndef UART_TX_REFERENCE_H
#define UART_TX_REFERENCE_H
#include <stddef.h>
#include <stdint.h>
#include "uart_tx_pool.h"
#ifdef __cplusplus
extern "C" {
#endif
/* HAL-independent subset for log backends. Task context only.
 * Success transfers one immutable owner; failure leaves ownership with caller.
 * release runs in the TX task after DMA completion/confirmed stop. An unsafe
 * abort pins the owner instead of making DMA-accessed storage reusable. */
uint8_t UART_Async_IsReady(void);
size_t UART_Async_SubmitReference(const uint8_t *data, size_t length,
    UartTxReleaseFn release, uint32_t context, uint32_t timeout_ms);
/* Only truly static immutable storage, not an arbitrary const/reusable buffer. */
size_t UART_Async_WriteStatic(const uint8_t *data, size_t length);
#ifdef __cplusplus
}
#endif
#endif
