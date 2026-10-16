#include "router.h"
#include "router_network.h"
#include "queue.h"
#include "task.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static StaticQueue_t queues[2];
static uint8_t storage[2][8U * sizeof(RouterPacket_t)];
static unsigned created, uart_count, esp_count, line_count;
static TickType_t tick;
static RouterPacket_t uart_packet, esp_packet;
QueueHandle_t xQueueCreate(UBaseType_t depth, UBaseType_t size)
{
    assert(created < 2 && depth <= 8 && size == sizeof(RouterPacket_t));
    StaticQueue_t *q = &queues[created];
    *q = (StaticQueue_t){depth, size, 0, 0, storage[created++]};
    return q;
}
BaseType_t xQueueSend(QueueHandle_t q, const void *item, TickType_t wait)
{
    (void)wait;
    if (q->count == q->depth) return pdFALSE;
    memcpy(q->storage + ((q->head + q->count) % q->depth) * q->item_size, item, q->item_size);
    ++q->count; return pdPASS;
}
BaseType_t xQueueReceive(QueueHandle_t q, void *item, TickType_t wait)
{
    (void)wait;
    if (!q->count) return pdFALSE;
    memcpy(item, q->storage + q->head * q->item_size, q->item_size);
    q->head = (q->head + 1) % q->depth; --q->count; return pdPASS;
}
TickType_t xTaskGetTickCount(void) { return tick; }
UBaseType_t uxQueueMessagesWaiting(QueueHandle_t q) { return (UBaseType_t)q->count; }
static uint8_t uart_tx(const RouterPacket_t *p) { uart_packet = *p; ++uart_count; return 1; }
static uint8_t esp_tx(const RouterPacket_t *p) { esp_packet = *p; ++esp_count; return 1; }
static void line(void *context, const char *text)
{ (void)context; assert(rn_line_allowed(text)); ++line_count; }
static void receive(RouterPort_t port, unsigned src, unsigned dst, unsigned type,
                    unsigned seq, unsigned ttl, const char *payload)
{
    char text[321];
    snprintf(text, sizeof(text), "@R1 %u %u %u %u %u %u %s", src, dst, type, seq,
             ttl, (unsigned)strlen(payload), payload);
    assert(Router_SubmitAsciiLine(port, text)); Router_Service(8);
}
static bool has_route(uint16_t node)
{
    RouterRouteInfo_t route;
    for (uint32_t i=0; i<Router_GetRouteCount(); ++i)
        if (Router_GetRoute(i, &route) && route.destination == node) return true;
    return false;
}
int main(void)
{
    rn_frame_t frame;
    rn_message_t message;
    assert(rn_parse("@R1 4 1 7 12 8 7 PING 42", &frame));
    assert(rn_line_allowed("@R1 4 1 7 12 8 7 PING 42"));
    assert(!rn_line_allowed("@R1 4 1 1 12 8 7 1 START"));
    assert(!rn_line_allowed("@R1 4 1 7 12 8 7 1 START"));
    assert(!rn_line_allowed("@R1 4 1 7 12 8 6 PING 0"));
    assert(!rn_line_allowed("@R1 4 1 7 12 9 6 PING 1"));
    assert(!rn_line_allowed("@R1 4 1 7 12 8 8 PONG 1 5"));
    assert(!rn_parse("@R1 999999999999999999999 1 7 1 8 6 PING 1", &frame));
    assert(!rn_message_parse("INFO 1 4 4294967296 1 1 1", &message));
    assert(rn_message_parse("INFO 65535 4 4294967295 1 1 1", &message));
    assert(!rn_message_parse("PING 1 FW END", &message));
    assert(!rn_message_parse("PING +1", &message));
    rn_stream_t stream = {0};
    const char *wire = "@R1 4 1 7 12 8 7 PING 42\r\n@R1 4 1 7 13 8 8 STATUS 1\n";
    for (size_t i=0; i<strlen(wire); ++i) rn_stream_feed(&stream, (const uint8_t *)wire+i, 1, line, NULL);
    assert(line_count == 2);
    uint8_t junk[400]; memset(junk, 'x', sizeof(junk));
    rn_stream_feed(&stream, junk, sizeof(junk), line, NULL);
    assert(stream.used == 0 && stream.dropping && stream.rejected == 1);
    rn_stream_feed(&stream, (const uint8_t *)"\n", 1, line, NULL);
    rn_stream_feed(&stream, (const uint8_t *)wire, strlen(wire), line, NULL);
    assert(line_count == 4 && !stream.dropping);
    assert(Router_Init(1));
    Router_RegisterPortTx(ROUTER_PORT_UART1, uart_tx);
    Router_RegisterPortTx(ROUTER_PORT_ESP32, esp_tx);
    receive(ROUTER_PORT_ESP32, 2, 65535, 3, 1, 8, "HELLO");
    assert(has_route(2));
    receive(ROUTER_PORT_UART1, 4, 65535, 3, 1, 8, "HELLO");
    assert(has_route(4));
    receive(ROUTER_PORT_UART1, 4, 1, 7, 2, 8, "PING 42");
    assert(uart_packet.type == RN_DIAGNOSTIC_TYPE && !strcmp(uart_packet.payload, "PONG 42 1"));
    RouterPacket_t local;
    assert(!Router_LocalReadPacket(&local)); /* NOT actuator ProtocolTask. */
    receive(ROUTER_PORT_UART1, 4, 1, 7, 3, 8, "STATUS 43");
    assert(rn_message_parse(uart_packet.payload, &message) && message.kind == RN_INFO);
    receive(ROUTER_PORT_UART1, 4, 2, 7, 4, 8, "PING 44");
    assert(esp_packet.dst == 2 && esp_packet.ttl == 7 && !strcmp(esp_packet.payload, "PING 44"));
    unsigned previous = esp_count;
    receive(ROUTER_PORT_UART1, 4, 2, 7, 4, 8, "PING 44");
    assert(esp_count == previous);
    receive(ROUTER_PORT_UART1, 4, 2, 7, 5, 1, "PING 45");
    assert(esp_count == previous);
    receive(ROUTER_PORT_UART1, 5, 1, 7, 6, 8, "START 46");
    assert(!has_route(5) && !Router_LocalReadPacket(&local));
    receive(ROUTER_PORT_UART1, 4, 1, 4, 7, 8, "legacy-event");
    assert(Router_LocalReadPacket(&local) && local.type == 4);
    assert(!Router_LocalReadPacket(&local)); /* Existing event namespace retained. */
    RouterStatus_t status; Router_GetStatus(&status);
    assert(status.dropped_duplicate && status.dropped_ttl && status.parse_errors);
    assert(Router_SubmitAsciiLine(ROUTER_PORT_SOCKET, "@R1 9 65535 3 1 8 5 HELLO"));
    assert(Router_SubmitAsciiLine(ROUTER_PORT_UART1, "@R1 4 1 7 88 8 7 PING 88"));
    Router_ForgetPort(ROUTER_PORT_SOCKET);
    Router_Service(8);
    assert(!has_route(9) && !strcmp(uart_packet.payload, "PONG 88 1"));
    Router_ForgetPort(ROUTER_PORT_ESP32);
    assert(!has_route(2) && has_route(4));
    receive(ROUTER_PORT_ESP32, 2, 65535, 3, 1, 8, "HELLO");
    assert(has_route(2)); /* Restarted peer's old seq is valid in a new epoch. */
    tick = 16001; Router_Maintenance();
    assert(!has_route(4));
    for (unsigned i=0; i<8; ++i)
        assert(Router_SubmitAsciiLine(ROUTER_PORT_UART1, "@R1 4 1 7 99 8 6 PING 1"));
    assert(!Router_SubmitAsciiLine(ROUTER_PORT_UART1, "@R1 4 1 7 99 8 6 PING 1"));
    Router_Service(8); Router_GetStatus(&status); assert(status.rx_queue_full == 1);
    puts("PASS real Router: bounded wire, discovery, forwarding, diagnostic isolation, duplicate/TTL, aging, disconnect, queue-full");
    return 0;
}
