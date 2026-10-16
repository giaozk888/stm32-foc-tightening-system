#ifndef MODBUS_PROBE_H
#define MODBUS_PROBE_H

#include <stdint.h>

typedef enum {
    MODBUS_PROBE_OK = 0,
    MODBUS_PROBE_TIMEOUT,
    MODBUS_PROBE_CRC_ERROR,
    MODBUS_PROBE_BAD_FRAME,
    MODBUS_PROBE_EXCEPTION,
    MODBUS_PROBE_UART_ERROR,
    MODBUS_PROBE_BAD_ARGUMENT
} ModbusProbeResult_t;

typedef struct {
    uint16_t value;
    uint8_t exception_code;
    uint8_t received_bytes;
    uint32_t uart_error;
} ModbusProbeReply_t;

/* One bounded, read-only Modbus RTU request on USART3 PC10/PC11.
 * Functions 1/2 read eight bits; functions 3/4 read one register. */
ModbusProbeResult_t ModbusProbe_ReadOne(uint32_t baud,
                                      uint8_t slave,
                                      uint8_t function,
                                      uint16_t address,
                                      uint8_t even_parity,
                                      ModbusProbeReply_t *reply);

/* Manual FC05 relay command; relay 1..4, vendor defaults 9600 8N1 ID 255. */
ModbusProbeResult_t ModbusProbe_SetRelay(uint8_t relay,
                                       uint8_t on,
                                       ModbusProbeReply_t *reply);

#endif
