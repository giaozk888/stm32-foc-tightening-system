#include "uart_line_parser.h"

void UartLineParser_Init(UartLineParser *parser)
{
    parser->length = 0U;
    parser->discard = 0U;
}

void UartLineParser_Gap(UartLineParser *parser)
{
    parser->length = 0U;
    parser->discard = 1U;
}

int UartLineParser_Byte(UartLineParser *parser, uint8_t byte,
                        UartLineCallback callback, void *context)
{
    if ((byte == '\r') || (byte == '\n')) {
        if (!parser->discard && (parser->length != 0U)) {
            parser->line[parser->length] = '\0';
            if (callback != NULL) callback(parser->line, context);
        }
        parser->length = 0U;
        parser->discard = 0U;
    } else if (!parser->discard) {
        if ((byte == 0x08U) || (byte == 0x7FU)) {
            if (parser->length != 0U) --parser->length;
        } else if ((byte >= 0x20U) && (byte <= 0x7EU)) {
            if (parser->length < UART_LINE_CAPACITY - 1U) {
                parser->line[parser->length++] = (char)byte;
            } else {
                UartLineParser_Gap(parser);
                return -1;
            }
        }
    }
    return 0;
}
