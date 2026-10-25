#ifndef UART_LINE_PARSER_H
#define UART_LINE_PARSER_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define UART_LINE_CAPACITY 320U
typedef struct {
    char line[UART_LINE_CAPACITY];
    size_t length;
    uint8_t discard;
} UartLineParser;
typedef void (*UartLineCallback)(const char *line, void *context);
void UartLineParser_Init(UartLineParser *parser);
void UartLineParser_Gap(UartLineParser *parser);
/* Returns -1 once when a line becomes too long. No suffix is dispatched. */
int UartLineParser_Byte(UartLineParser *parser, uint8_t byte,
                        UartLineCallback callback, void *context);
#ifdef __cplusplus
}
#endif
#endif
