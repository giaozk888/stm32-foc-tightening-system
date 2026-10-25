#ifndef UART_FIRMWARE_TRANSFER_H
#define UART_FIRMWARE_TRANSFER_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Local UART only. No boot metadata writes, erase, reset, or motion here. */
enum {
    UART_FW_CHANNEL = 3,
    UART_FW_RESOURCE = 2,
    UART_FW_PACKET = 96,
    UART_FW_CAPACITY = 224 * 1024
};
enum { UART_FW_PREPARE = 1, UART_FW_WRITE = 2, UART_FW_COMPARE = 3, UART_FW_VERIFY = 4 };
enum {
    UART_FW_IDLE = 0,
    UART_FW_OPEN = 1,
    UART_FW_RECEIVING = 2,
    UART_FW_COMPLETE = 3,
    UART_FW_FAILED = 4
};
typedef struct {
    uint32_t ready, busy, phase, result, received, rejected;
} UartFirmwareTransferDiagnostics;
void PW_UartFirmwareTransfer_Init(void);
void PW_UartFirmwareTransfer_Service(void); /* ProtocolTask: sole Flash owner. */
int PW_UartFirmwareTransfer_Process(const uint8_t *data, size_t size, uint8_t local_uart);
int PW_UartFirmwareTransfer_Close(void); /* asynchronous; poll BUSY=0 */
int PW_UartFirmwareTransfer_Busy(void);
void PW_UartFirmwareTransfer_GetDiagnostics(UartFirmwareTransferDiagnostics *out);
size_t PW_UartFirmwareTransfer_Unhex(const char *text, uint8_t *out, size_t capacity);
/* Existing APP boundary: PREPARE runs in ProtocolTask; other ops use Service. */
int PW_UartFirmwareTransfer_Port(uint32_t operation, uint32_t offset, const uint8_t *data,
                                 size_t size, uint32_t *value);
/* Unsolicited, raw UART output. Must never use the console's reply route. */
int PW_UartFirmwareTransfer_Send(const uint8_t *data, size_t size);
#if defined(PW_TRANSFER_HOST)
void PW_UartFirmwareTransfer_Run(void);
void PW_UartFirmwareTransfer_Stop(void);
#endif
#ifdef __cplusplus
}
#endif
#endif
