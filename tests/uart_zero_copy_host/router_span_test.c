#include "router.h"
#include "queue.h"
#include "task.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static StaticQueue_t s_queues[2];
static uint8_t s_storage[2][8U * sizeof(RouterPacket_t)];
static unsigned int s_created, s_calls;
static RouterPacket_t s_packet;
static int s_transport_fail;
QueueHandle_t xQueueCreate(UBaseType_t depth, UBaseType_t item_size)
{
    assert(s_created < 2U && depth <= 8U && item_size == sizeof(RouterPacket_t));
    StaticQueue_t *queue = &s_queues[s_created];
    *queue = (StaticQueue_t){depth, item_size, 0U, 0U, s_storage[s_created++]};
    return queue;
}
BaseType_t xQueueSend(QueueHandle_t queue, const void *item, TickType_t ticks)
{
    (void)ticks;
    if (queue->count == queue->depth) return pdFALSE;
    memcpy(queue->storage + ((queue->head + queue->count) % queue->depth) * queue->item_size,
           item, queue->item_size);
    ++queue->count; return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t queue, void *item, TickType_t ticks)
{
    (void)ticks;
    if (queue->count == 0U) return pdFALSE;
    memcpy(item, queue->storage + queue->head * queue->item_size, queue->item_size);
    queue->head = (queue->head + 1U) % queue->depth;
    --queue->count; return pdTRUE;
}
TickType_t xTaskGetTickCount(void) { return 0U; }
static uint8_t Capture(const RouterPacket_t *packet)
{
    s_packet = *packet; ++s_calls;
    return s_transport_fail ? 0U : 1U;
}
int main(void)
{
    uint16_t seq = 0U;
    char ascii[300];
    char raw[] = {'h', 'e', 'l', 'l', 'o', '\r', '\n', 'x'}; /* no NUL */
    assert(Router_Init(1U));
    Router_RegisterPortTx(ROUTER_PORT_ESP32, Capture);
    assert(Router_SendSpan(ROUTER_BROADCAST_NODE, 6U, raw, 5U, &seq));
    assert(s_calls == 1U && seq == 1U && s_packet.length == 5U);
    assert(strcmp(s_packet.payload, "hello") == 0);
    memset(raw, '!', sizeof(raw)); /* Router owns its business representation */
    assert(Router_EncodeAsciiFrame(&s_packet, ascii, sizeof(ascii)) == strlen(ascii));
    assert(strcmp(ascii, "@R1 1 65535 6 1 8 5 hello") == 0);
    assert(Router_SendText(ROUTER_BROADCAST_NODE, 6U, "hello", &seq));
    assert(seq == 2U && s_packet.length == 5U && !strcmp(s_packet.payload, "hello"));
    assert(Router_SendSpan(1U, 6U, "local\r\n", 5U, &seq));
    RouterPacket_t local;
    assert(Router_LocalReadPacket(&local) && !strcmp(local.payload, "hello"));
    assert(Router_LocalReadPacket(&local) && !strcmp(local.payload, "hello"));
    assert(Router_LocalReadPacket(&local) && !strcmp(local.payload, "local"));
    assert(!Router_LocalReadPacket(&local));
    char max[ROUTER_MAX_PAYLOAD]; memset(max, 'z', sizeof(max));
    assert(Router_SendSpan(ROUTER_BROADCAST_NODE, 6U, max, sizeof(max), NULL));
    assert(s_packet.length == sizeof(max) && s_packet.payload[sizeof(max)] == '\0');
    assert(!Router_SendSpan(2U, 6U, "no route", 8U, NULL));
    s_transport_fail = 1;
    assert(!Router_SendSpan(ROUTER_BROADCAST_NODE, 6U, "failed", 6U, NULL));
    assert(!Router_SendSpan(1U, 6U, NULL, 1U, NULL));
    assert(!Router_SendSpan(1U, 6U, max, 0U, NULL));
    assert(!Router_SendSpan(1U, 6U, max, sizeof(max) + 1U, NULL));
    puts("PASS: real Router span bounded copy, trimmed CRLF, ASCII wire, legacy API, failure paths");
    return 0;
}
