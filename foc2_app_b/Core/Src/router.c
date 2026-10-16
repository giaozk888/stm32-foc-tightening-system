#include "router.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(ESP_PLATFORM)
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#else
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#endif

#if defined(ESP_PLATFORM)
/* This file is also the ESP32 Router core. ESP-IDF critical sections require
 * an explicit SMP spinlock; the override is local to this translation unit. */
static portMUX_TYPE g_router_mux = portMUX_INITIALIZER_UNLOCKED;
#undef taskENTER_CRITICAL
#undef taskEXIT_CRITICAL
#define taskENTER_CRITICAL() portENTER_CRITICAL(&g_router_mux)
#define taskEXIT_CRITICAL() portEXIT_CRITICAL(&g_router_mux)
#endif

#if defined(ROUTER_READ_ONLY_NETWORK)
#include "router_network.h"
#if defined(ROUTER_READ_ONLY_RPC)
#include "router_rpc_wire.h"
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
#include "router_transfer_wire.h"
#endif
/* Keep diagnostic formatting out of the common discovery/forwarding frame.
 * GCC otherwise folds its buffers into Router_Service's always-live stack. */
static __attribute__((noinline)) void Router_Diagnostic(const RouterPacket_t *packet)
{
    rn_message_t message;
    RouterStatus_t status;
    char reply[128];
    if (!rn_message_parse(packet->payload, &message)) return;
    Router_GetStatus(&status);
    if (message.kind == RN_PING)
        (void)snprintf(reply, sizeof(reply), "PONG %u %u",
                       (unsigned)message.nonce, (unsigned)status.local_node_id);
    else if (message.kind == RN_STATUS) {
        (void)snprintf(reply, sizeof(reply), "INFO %u %u %lu %lu %lu %lu",
            (unsigned)message.nonce, (unsigned)status.local_node_id,
            (unsigned long)status.rx_packets, (unsigned long)status.tx_packets,
            (unsigned long)status.dropped_no_route, (unsigned long)status.dropped_duplicate);
    } else return; /* Responses never enter the actuator console. */
    (void)Router_SendText(packet->src, RN_DIAGNOSTIC_TYPE, reply, NULL);
}
#endif

typedef struct
{
    uint8_t used;
    uint16_t node_id;
    RouterPort_t port;
    uint8_t flags;
    TickType_t last_seen_tick;
    uint32_t rx_packets;
} RouterNodeEntry_t;

typedef struct
{
    uint8_t used;
    uint16_t destination;
    RouterPort_t port;
    uint8_t metric;
    uint8_t flags;
    TickType_t last_seen_tick;
} RouterRouteEntry_t;

typedef struct
{
    uint8_t used;
    uint16_t src;
    uint16_t seq;
    uint8_t type;
    TickType_t seen_tick;
#if defined(ROUTER_READ_ONLY_TRANSFER)
    uint32_t transfer_id, transfer_crc;
    uint16_t transfer_offset;
#endif
} RouterDupEntry_t;

static QueueHandle_t g_rx_queue = NULL;
static QueueHandle_t g_local_queue = NULL;

static RouterPortTxFn g_port_tx[ROUTER_PORT_COUNT];
#if defined(ROUTER_READ_ONLY_NETWORK)
static uint32_t g_port_epoch[ROUTER_PORT_COUNT];
#endif

static RouterNodeEntry_t g_nodes[ROUTER_MAX_NODES];
static RouterRouteEntry_t g_routes[ROUTER_MAX_ROUTES];
static RouterDupEntry_t g_dup_cache[ROUTER_DUP_CACHE_SIZE];

static RouterStatus_t g_status;
#if defined(ROUTER_READ_ONLY_NETWORK)
#define Router_Count(field) do { taskENTER_CRITICAL(); ++g_status.field; taskEXIT_CRITICAL(); } while (0)
#else
#define Router_Count(field) g_status.field++
#endif

static uint16_t g_next_seq = 1U;
static uint32_t g_dup_replace_index = 0U;

static TickType_t g_last_discovery_tick = 0U;
static TickType_t g_last_maintenance_tick = 0U;


static uint32_t Router_TicksToMs(TickType_t ticks)
{
    return (uint32_t)(ticks * portTICK_PERIOD_MS);
}


static uint32_t Router_AgeMsFrom(TickType_t now,
                                 TickType_t then)
{
    return Router_TicksToMs(now - then);
}


static uint32_t Router_AgeMs(TickType_t then)
{
    return Router_AgeMsFrom(xTaskGetTickCount(), then);
}


static uint8_t Router_PortValid(RouterPort_t port)
{
    return (((uint32_t)port) < ((uint32_t)ROUTER_PORT_COUNT)) ? 1U : 0U;
}


const char *Router_PortName(RouterPort_t port)
{
    switch (port)
    {
        case ROUTER_PORT_LOCAL:  return "LOCAL";
        case ROUTER_PORT_UART1:  return "UART1";
        case ROUTER_PORT_USB:    return "USB";
        case ROUTER_PORT_SOCKET: return "SOCKET";
        case ROUTER_PORT_ESP32:  return "ESP32";
        default:                 return "UNKNOWN";
    }
}


static int32_t Router_FindNode(uint16_t node_id)
{
    uint32_t i;

    for (i = 0U; i < ROUTER_MAX_NODES; i++)
    {
        if ((g_nodes[i].used != 0U) &&
            (g_nodes[i].node_id == node_id))
        {
            return (int32_t)i;
        }
    }

    return -1;
}


static int32_t Router_FindRoute(uint16_t destination)
{
    uint32_t i;

    for (i = 0U; i < ROUTER_MAX_ROUTES; i++)
    {
        if ((g_routes[i].used != 0U) &&
            (g_routes[i].destination == destination))
        {
            return (int32_t)i;
        }
    }

    return -1;
}


static uint8_t Router_IsDiscoveryPayload(const RouterPacket_t *packet,
                                         const char *text)
{
    size_t len;

    if ((packet == NULL) ||
        (text == NULL) ||
        (packet->type != ROUTER_PKT_DISCOVERY))
    {
        return 0U;
    }

    len = strlen(text);

    if ((packet->length != len) ||
        (memcmp(packet->payload, text, len) != 0))
    {
        return 0U;
    }

    return 1U;
}


static void Router_LearnSource(uint16_t src,
                               RouterPort_t ingress_port,
                               uint8_t discovery)
{
    int32_t idx;
    uint32_t i;
    TickType_t now;

    if ((src == 0U) ||
        (src == ROUTER_BROADCAST_NODE) ||
        (src == g_status.local_node_id) ||
        (ingress_port == ROUTER_PORT_LOCAL))
    {
        return;
    }

    now = xTaskGetTickCount();

    taskENTER_CRITICAL();

    idx = Router_FindNode(src);

    if (idx < 0)
    {
        for (i = 0U; i < ROUTER_MAX_NODES; i++)
        {
            if (g_nodes[i].used == 0U)
            {
                idx = (int32_t)i;
                memset(&g_nodes[i], 0, sizeof(g_nodes[i]));
                g_nodes[i].used = 1U;
                g_nodes[i].node_id = src;
                g_nodes[i].flags = ROUTER_NODE_FLAG_LEARNED;
                break;
            }
        }
    }

    if (idx >= 0)
    {
        g_nodes[idx].port = ingress_port;
        g_nodes[idx].last_seen_tick = now;
        g_nodes[idx].rx_packets++;

        if (discovery != 0U)
        {
            g_nodes[idx].flags |= ROUTER_NODE_FLAG_DISCOVERED;
        }
    }

    idx = Router_FindRoute(src);

    if (idx < 0)
    {
        for (i = 0U; i < ROUTER_MAX_ROUTES; i++)
        {
            if (g_routes[i].used == 0U)
            {
                idx = (int32_t)i;
                memset(&g_routes[i], 0, sizeof(g_routes[i]));
                g_routes[i].used = 1U;
                g_routes[i].destination = src;
                g_routes[i].flags = ROUTER_ROUTE_FLAG_LEARNED;
                break;
            }
        }
    }

    if (idx >= 0)
    {
        g_routes[idx].port = ingress_port;
        g_routes[idx].metric = 1U;
        g_routes[idx].last_seen_tick = now;

        if (discovery != 0U)
        {
            g_routes[idx].flags |= ROUTER_ROUTE_FLAG_DISCOVERY;
        }
    }

    taskEXIT_CRITICAL();
}


static uint8_t Router_QueueLocal(const RouterPacket_t *packet)
{
    if ((packet == NULL) || (g_local_queue == NULL))
    {
        return 0U;
    }

    if (xQueueSend(g_local_queue, packet, 0U) != pdPASS)
    {
        Router_Count(local_queue_full);
        return 0U;
    }

    Router_Count(local_delivered);
    return 1U;
}


static uint8_t Router_TxPort(RouterPort_t port,
                             const RouterPacket_t *packet)
{
    RouterPortTxFn tx_fn;

    if ((packet == NULL) ||
        (Router_PortValid(port) == 0U) ||
        (port == ROUTER_PORT_LOCAL))
    {
        return 0U;
    }

    tx_fn = g_port_tx[port];

    if (tx_fn == NULL)
    {
        return 0U;
    }

    if (tx_fn(packet) == 0U)
    {
        return 0U;
    }

    Router_Count(tx_packets);
    return 1U;
}


static uint8_t Router_Forward(RouterPacket_t *packet)
{
    int32_t idx;
    RouterPort_t port;

    if (packet == NULL)
    {
        return 0U;
    }

    if (packet->ttl <= 1U)
    {
        Router_Count(dropped_ttl);
        return 0U;
    }

    idx = Router_FindRoute(packet->dst);

    if (idx < 0)
    {
        Router_Count(dropped_no_route);
        return 0U;
    }

    port = g_routes[idx].port;

    /*
     * A route pointing back to the ingress transport would immediately
     * reflect the packet and create a one-link loop.
     */
    if (port == packet->ingress_port)
    {
        Router_Count(dropped_self_loop);
        return 0U;
    }

    packet->ttl--;

    if (Router_TxPort(port, packet) == 0U)
    {
        Router_Count(dropped_no_route);
        return 0U;
    }

    Router_Count(forwarded);
    return 1U;
}


static uint8_t Router_DuplicateSeen(const RouterPacket_t *packet)
{
    uint32_t i;
    TickType_t now;
    int32_t free_idx = -1;
    int32_t expired_idx = -1;

    /*
     * Legacy Protocol V2 commands are represented as src=0/seq=0 and must
     * never pass through duplicate suppression.
     */
    if ((packet == NULL) ||
        (packet->src == 0U) ||
#if defined(ROUTER_READ_ONLY_TRANSFER)
        (packet->seq == 0U && packet->type != RN_TRANSFER_TYPE))
#else
        (packet->seq == 0U))
#endif
    {
        return 0U;
    }

    now = xTaskGetTickCount();

#if defined(ROUTER_READ_ONLY_TRANSFER)
    rn_transfer_fragment_t transfer = {0};
    if (packet->type == RN_TRANSFER_TYPE &&
        !rn_transfer_parse(packet->payload, &transfer)) return 1U;
#endif
    taskENTER_CRITICAL();

    for (i = 0U; i < ROUTER_DUP_CACHE_SIZE; i++)
    {
        if (g_dup_cache[i].used == 0U)
        {
            if (free_idx < 0)
            {
                free_idx = (int32_t)i;
            }
            continue;
        }

        if (Router_AgeMsFrom(now, g_dup_cache[i].seen_tick) >
            ROUTER_DUP_WINDOW_MS)
        {
            if (expired_idx < 0)
            {
                expired_idx = (int32_t)i;
            }
            continue;
        }

#if defined(ROUTER_READ_ONLY_TRANSFER)
        if (packet->type == RN_TRANSFER_TYPE) {
            if (g_dup_cache[i].src == packet->src && g_dup_cache[i].type == RN_TRANSFER_TYPE &&
                g_dup_cache[i].transfer_id == transfer.id &&
                g_dup_cache[i].transfer_crc == transfer.crc &&
                g_dup_cache[i].transfer_offset == transfer.offset) {
                taskEXIT_CRITICAL();
                return 1U;
            }
            continue; /* R1 seq may restart across an upstream TCP reconnect. */
        }
#endif
        if ((g_dup_cache[i].src == packet->src) &&
            (g_dup_cache[i].seq == packet->seq) &&
            (g_dup_cache[i].type == packet->type))
        {
            taskEXIT_CRITICAL();
            return 1U;
        }
    }

    if (free_idx < 0)
    {
        free_idx = expired_idx;
    }

    if (free_idx < 0)
    {
        free_idx = (int32_t)(g_dup_replace_index %
                             ROUTER_DUP_CACHE_SIZE);

        g_dup_replace_index++;
    }

    g_dup_cache[free_idx].used = 1U;
    g_dup_cache[free_idx].src = packet->src;
    g_dup_cache[free_idx].seq = packet->seq;
    g_dup_cache[free_idx].type = packet->type;
    g_dup_cache[free_idx].seen_tick = now;
#if defined(ROUTER_READ_ONLY_TRANSFER)
    g_dup_cache[free_idx].transfer_id = transfer.id;
    g_dup_cache[free_idx].transfer_crc = transfer.crc;
    g_dup_cache[free_idx].transfer_offset = transfer.offset;
#endif

    taskEXIT_CRITICAL();

    return 0U;
}


static uint8_t Router_ParseUnsigned(const char **cursor,
                                    unsigned long max_value,
                                    unsigned long *out)
{
    const char *p;
    char *endptr;
    unsigned long value;

    if ((cursor == NULL) ||
        (*cursor == NULL) ||
        (out == NULL))
    {
        return 0U;
    }

    p = *cursor;

    while ((*p == ' ') || (*p == '\t'))
    {
        p++;
    }

    if (*p == '\0')
    {
        return 0U;
    }

    value = strtoul(p, &endptr, 10);

    if ((endptr == p) || (value > max_value))
    {
        return 0U;
    }

    if ((*endptr != ' ') && (*endptr != '\t'))
    {
        return 0U;
    }

    *out = value;
    *cursor = endptr;

    return 1U;
}


static uint8_t Router_DecodeAsciiFrame(RouterPort_t ingress_port,
                                       const char *line,
                                       RouterPacket_t *packet)
{
    const char *p;
    unsigned long src;
    unsigned long dst;
    unsigned long type;
    unsigned long seq;
    unsigned long ttl;
    unsigned long length;
    size_t actual_length;

    if ((line == NULL) || (packet == NULL))
    {
        return 0U;
    }

    if (strncmp(line, "@R1 ", 4U) != 0)
    {
        return 0U;
    }

    p = line + 4U;

    if ((Router_ParseUnsigned(&p, 0xFFFFUL, &src) == 0U) ||
        (Router_ParseUnsigned(&p, 0xFFFFUL, &dst) == 0U) ||
        (Router_ParseUnsigned(&p, 0xFFUL, &type) == 0U) ||
        (Router_ParseUnsigned(&p, 0xFFFFUL, &seq) == 0U) ||
        (Router_ParseUnsigned(&p, 0xFFUL, &ttl) == 0U) ||
        (Router_ParseUnsigned(&p, ROUTER_MAX_PAYLOAD, &length) == 0U))
    {
        return 0U;
    }

    while ((*p == ' ') || (*p == '\t'))
    {
        p++;
    }

    actual_length = strlen(p);

    if ((actual_length != (size_t)length) ||
        (actual_length > ROUTER_MAX_PAYLOAD) ||
        (ttl == 0UL))
    {
        return 0U;
    }

    memset(packet, 0, sizeof(*packet));

    packet->src = (uint16_t)src;
    packet->dst = (uint16_t)dst;
    packet->type = (uint8_t)type;
    packet->seq = (uint16_t)seq;
    packet->ttl = (uint8_t)ttl;
    packet->length = (uint16_t)length;
    packet->ingress_port = ingress_port;

    memcpy(packet->payload, p, actual_length + 1U);

    return 1U;
}


#include "../../../firmware_common/router_ascii_encoder.inc"


static uint16_t Router_AllocateSeq(void)
{
    uint16_t seq;

    taskENTER_CRITICAL();

    seq = g_next_seq++;

    if (g_next_seq == 0U)
    {
        g_next_seq = 1U;
    }

    taskEXIT_CRITICAL();

    return seq;
}


static uint8_t Router_SendPacketSpan(uint16_t dst, uint8_t type,
                                      const char *payload, size_t len, uint16_t *out_seq);
static uint8_t Router_SendPacket(uint16_t dst, uint8_t type,
                                 const char *payload, uint16_t *out_seq)
{
    return Router_SendPacketSpan(dst, type, payload,
                                 payload != NULL ? strlen(payload) : 0U, out_seq);
}

static uint8_t Router_SendPacketSpan(uint16_t dst,
                                 uint8_t type,
                                 const char *payload,
                                 size_t len,
                                 uint16_t *out_seq)
{
    RouterPacket_t packet;
    int32_t route_idx;
    uint16_t seq;

    if (payload == NULL)
    {
        return 0U;
    }

    if ((len == 0U) ||
        (len > ROUTER_MAX_PAYLOAD))
    {
        return 0U;
    }

    seq = Router_AllocateSeq();

    memset(&packet, 0, sizeof(packet));

    packet.src = g_status.local_node_id;
    packet.dst = dst;
    packet.type = type;
    packet.seq = seq;
    packet.ttl = ROUTER_DEFAULT_TTL;
    packet.length = (uint16_t)len;
    packet.ingress_port = ROUTER_PORT_LOCAL;

    memcpy(packet.payload, payload, len);
    packet.payload[len] = '\0';

    if (out_seq != NULL)
    {
        *out_seq = seq;
    }

    if (dst == g_status.local_node_id)
    {
        (void)Router_QueueLocal(&packet);
        return 1U;
    }

    if (dst == ROUTER_BROADCAST_NODE)
    {
        uint32_t port;
        uint8_t sent = 0U;

        /*
         * Router control-plane broadcasts (HELLO/ANNOUNCE) are consumed by
         * Router Core and must NOT be delivered to the application Protocol
         * V2 parser.  Doing so would make "HELLO" look like a legacy command
         * without a request ID and produce:
         *
         *   0 ERR 103 BAD_REQUEST_ID
         *
         * Application broadcast packets may still be delivered locally.
         */
        if (type != ROUTER_PKT_DISCOVERY)
        {
            (void)Router_QueueLocal(&packet);
        }

        for (port = 1U; port < ROUTER_PORT_COUNT; port++)
        {
            if (g_port_tx[port] != NULL)
            {
                sent |= Router_TxPort(
                    (RouterPort_t)port,
                    &packet);
            }
        }

        return sent;
    }

    route_idx = Router_FindRoute(dst);

    if (route_idx < 0)
    {
        Router_Count(dropped_no_route);
        return 0U;
    }

    if (Router_TxPort(
            g_routes[route_idx].port,
            &packet) == 0U)
    {
        Router_Count(dropped_no_route);
        return 0U;
    }

    return 1U;
}


static uint8_t Router_SendAnnounce(uint16_t destination)
{
    uint16_t ignored_seq = 0U;

    if (Router_SendPacket(
            destination,
            ROUTER_PKT_DISCOVERY,
            ROUTER_DISCOVERY_ANNOUNCE_TEXT,
            &ignored_seq) == 0U)
    {
        return 0U;
    }

    Router_Count(discovery_tx);
    return 1U;
}


uint8_t Router_SendHello(uint16_t *out_seq)
{
    if (Router_SendPacket(
            ROUTER_BROADCAST_NODE,
            ROUTER_PKT_DISCOVERY,
            ROUTER_DISCOVERY_HELLO_TEXT,
            out_seq) == 0U)
    {
        return 0U;
    }

    Router_Count(discovery_tx);
    g_last_discovery_tick = xTaskGetTickCount();

    return 1U;
}


uint8_t Router_Init(uint16_t local_node_id)
{
    memset(&g_status, 0, sizeof(g_status));
    memset(g_nodes, 0, sizeof(g_nodes));
    memset(g_routes, 0, sizeof(g_routes));
    memset(g_dup_cache, 0, sizeof(g_dup_cache));
    memset(g_port_tx, 0, sizeof(g_port_tx));
#if defined(ROUTER_READ_ONLY_NETWORK)
    memset(g_port_epoch, 0, sizeof(g_port_epoch));
#endif

    if ((local_node_id == 0U) ||
        (local_node_id == ROUTER_BROADCAST_NODE))
    {
        return 0U;
    }

    g_rx_queue = xQueueCreate(
        ROUTER_RX_QUEUE_DEPTH,
        sizeof(RouterPacket_t));

    g_local_queue = xQueueCreate(
        ROUTER_LOCAL_QUEUE_DEPTH,
        sizeof(RouterPacket_t));

    if ((g_rx_queue == NULL) ||
        (g_local_queue == NULL))
    {
        return 0U;
    }

    g_status.local_node_id = local_node_id;
    g_next_seq = 1U;
    g_dup_replace_index = 0U;

    g_nodes[0].used = 1U;
    g_nodes[0].node_id = local_node_id;
    g_nodes[0].port = ROUTER_PORT_LOCAL;
    g_nodes[0].flags =
        ROUTER_NODE_FLAG_LOCAL |
        ROUTER_NODE_FLAG_STATIC;
    g_nodes[0].last_seen_tick = xTaskGetTickCount();

    g_last_discovery_tick = xTaskGetTickCount();
    g_last_maintenance_tick = xTaskGetTickCount();

    return 1U;
}


void Router_RegisterPortTx(RouterPort_t port,
                           RouterPortTxFn tx_fn)
{
    if ((Router_PortValid(port) != 0U) &&
        (port != ROUTER_PORT_LOCAL))
    {
        g_port_tx[port] = tx_fn;
    }
}


uint8_t Router_SubmitAsciiLine(RouterPort_t ingress_port,
                               const char *line)
{
    RouterPacket_t packet;
    size_t len;

    if ((line == NULL) ||
        (g_rx_queue == NULL) ||
        (Router_PortValid(ingress_port) == 0U))
    {
        return 0U;
    }

    len = strlen(line);

    if (len == 0U)
    {
        return 1U;
    }

    if (strncmp(line, "@R1 ", 4U) == 0)
    {
        if (Router_DecodeAsciiFrame(
                ingress_port,
                line,
                &packet) == 0U)
        {
            Router_Count(parse_errors);
            return 0U;
        }
    }
    else
    {
        /*
         * Legacy Protocol V2 line:
         * transparently deliver to this node.
         */
        if (len > ROUTER_MAX_PAYLOAD)
        {
            Router_Count(parse_errors);
            return 0U;
        }

        memset(&packet, 0, sizeof(packet));

        packet.src = 0U;
        packet.dst = g_status.local_node_id;
        packet.type = ROUTER_PKT_PROTOCOL;
        packet.seq = 0U;
        packet.ttl = ROUTER_DEFAULT_TTL;
        packet.length = (uint16_t)len;
        packet.ingress_port = ingress_port;

        memcpy(packet.payload, line, len + 1U);
    }

#if defined(ROUTER_READ_ONLY_NETWORK)
    taskENTER_CRITICAL();
    packet.ingress_epoch = g_port_epoch[ingress_port];
    taskEXIT_CRITICAL();
#endif
    if (xQueueSend(
            g_rx_queue,
            &packet,
            0U) != pdPASS)
    {
        Router_Count(rx_queue_full);
        return 0U;
    }

    return 1U;
}


void Router_Service(uint32_t max_packets)
{
    RouterPacket_t packet;
    uint32_t processed = 0U;

    if (g_rx_queue == NULL)
    {
        return;
    }

    while ((max_packets == 0U) ||
           (processed < max_packets))
    {
        uint8_t is_discovery;

        if (xQueueReceive(
                g_rx_queue,
                &packet,
                0U) != pdPASS)
        {
            break;
        }

        processed++;
        Router_Count(rx_packets);

#if defined(ROUTER_READ_ONLY_NETWORK)
        taskENTER_CRITICAL();
        uint8_t stale = packet.ingress_epoch != g_port_epoch[packet.ingress_port];
        taskEXIT_CRITICAL();
        if (stale) { Router_Count(parse_errors); continue; }
        if (packet.type == RN_DIAGNOSTIC_TYPE &&
            !rn_allowed(packet.src, packet.dst, packet.type, packet.ttl, packet.payload)) {
            Router_Count(parse_errors);
            continue;
        }
#if defined(ROUTER_READ_ONLY_TRANSFER)
        if (packet.type == RN_TRANSFER_TYPE &&
            !rn_allowed(packet.src, packet.dst, packet.type, packet.ttl, packet.payload)) {
            Router_Count(parse_errors);
            continue;
        }
#endif
#if defined(ROUTER_READ_ONLY_RPC)
        if (packet.type == RN_RPC_TYPE &&
            !rn_allowed(packet.src, packet.dst, packet.type, packet.ttl, packet.payload)) {
            Router_Count(parse_errors);
            continue;
        }
#endif
#endif

        /*
         * Packets sourced by ourselves but arriving from an external port are
         * a reflected loop and must not be forwarded again.
         */
        if ((packet.src == g_status.local_node_id) &&
            (packet.ingress_port != ROUTER_PORT_LOCAL))
        {
            Router_Count(dropped_self_loop);
            continue;
        }

        if (Router_DuplicateSeen(&packet) != 0U)
        {
            Router_Count(dropped_duplicate);
            continue;
        }

        is_discovery =
            (packet.type == ROUTER_PKT_DISCOVERY) ? 1U : 0U;

        Router_LearnSource(
            packet.src,
            packet.ingress_port,
            is_discovery);

        if (is_discovery != 0U)
        {
            Router_Count(discovery_rx);

            /*
             * HELLO is a broadcast probe.
             * Learning its source creates the reverse route immediately, so
             * ANNOUNCE can be sent unicast back to the discovered node.
             */
            if ((Router_IsDiscoveryPayload(
                    &packet,
                    ROUTER_DISCOVERY_HELLO_TEXT) != 0U) &&
                (packet.src != 0U) &&
                (packet.src != g_status.local_node_id))
            {
                (void)Router_SendAnnounce(packet.src);
            }

            /*
             * Discovery packets are consumed by the router control plane.
             * They are not passed into Protocol V2.
             */
        }
#if defined(ROUTER_READ_ONLY_NETWORK)
        else if (packet.type == RN_DIAGNOSTIC_TYPE &&
                 packet.dst == g_status.local_node_id)
        {
            Router_Diagnostic(&packet);
        }
#endif
        else if ((packet.dst == g_status.local_node_id) ||
                 (packet.dst == ROUTER_BROADCAST_NODE))
        {
            (void)Router_QueueLocal(&packet);
        }

        if ((packet.dst != g_status.local_node_id) &&
            (packet.dst != ROUTER_BROADCAST_NODE))
        {
            (void)Router_Forward(&packet);
        }
        else if (packet.dst == ROUTER_BROADCAST_NODE)
        {
            uint32_t port;
            RouterPacket_t forwarded = packet;

            if (forwarded.ttl <= 1U)
            {
                Router_Count(dropped_ttl);
                continue;
            }

            forwarded.ttl--;

            for (port = 1U;
                 port < ROUTER_PORT_COUNT;
                 port++)
            {
                if (((RouterPort_t)port != packet.ingress_port) &&
                    (g_port_tx[port] != NULL))
                {
                    if (Router_TxPort(
                            (RouterPort_t)port,
                            &forwarded) != 0U)
                    {
                        Router_Count(forwarded);
                    }
                }
            }
        }
    }
}


void Router_ClearDynamic(void)
{
    uint32_t i;

    taskENTER_CRITICAL();

    for (i = 0U; i < ROUTER_MAX_NODES; i++)
    {
        if ((g_nodes[i].used != 0U) &&
            ((g_nodes[i].flags & ROUTER_NODE_FLAG_STATIC) == 0U))
        {
            memset(&g_nodes[i], 0, sizeof(g_nodes[i]));
        }
    }

    for (i = 0U; i < ROUTER_MAX_ROUTES; i++)
    {
        if ((g_routes[i].used != 0U) &&
            ((g_routes[i].flags & ROUTER_ROUTE_FLAG_STATIC) == 0U))
        {
            memset(&g_routes[i], 0, sizeof(g_routes[i]));
        }
    }

    memset(g_dup_cache, 0, sizeof(g_dup_cache));

    taskEXIT_CRITICAL();
}

#if defined(ROUTER_READ_ONLY_NETWORK)
void Router_ForgetPort(RouterPort_t port)
{
    if (Router_PortValid(port) == 0U) return;
    taskENTER_CRITICAL();
    ++g_port_epoch[port]; /* Old queued packets will be dropped by Service. */
    for (uint32_t i = 0; i < ROUTER_MAX_NODES; ++i)
        if (g_nodes[i].used && g_nodes[i].port == port &&
            !(g_nodes[i].flags & (ROUTER_NODE_FLAG_LOCAL | ROUTER_NODE_FLAG_STATIC))) {
            for (uint32_t j = 0; j < ROUTER_DUP_CACHE_SIZE; ++j)
                if (g_dup_cache[j].used && g_dup_cache[j].src == g_nodes[i].node_id)
                    memset(&g_dup_cache[j], 0, sizeof(g_dup_cache[j]));
            memset(&g_nodes[i], 0, sizeof(g_nodes[i]));
        }
    for (uint32_t i = 0; i < ROUTER_MAX_ROUTES; ++i)
        if (g_routes[i].used && g_routes[i].port == port &&
            !(g_routes[i].flags & ROUTER_ROUTE_FLAG_STATIC))
            memset(&g_routes[i], 0, sizeof(g_routes[i]));
    taskEXIT_CRITICAL();
}
uint32_t Router_PortEpoch(RouterPort_t port)
{
    if (port <= ROUTER_PORT_LOCAL || port >= ROUTER_PORT_COUNT) return UINT32_MAX;
    taskENTER_CRITICAL();
    uint32_t epoch = g_port_epoch[port];
    taskEXIT_CRITICAL();
    return epoch;
}
#endif


void Router_Maintenance(void)
{
    TickType_t now;
    uint32_t i;

    now = xTaskGetTickCount();

    if (Router_AgeMsFrom(
            now,
            g_last_maintenance_tick) <
        ROUTER_MAINTENANCE_PERIOD_MS)
    {
        return;
    }

    g_last_maintenance_tick = now;

    taskENTER_CRITICAL();

    for (i = 0U; i < ROUTER_MAX_NODES; i++)
    {
        if ((g_nodes[i].used != 0U) &&
            ((g_nodes[i].flags & ROUTER_NODE_FLAG_STATIC) == 0U) &&
            (Router_AgeMsFrom(
                 now,
                 g_nodes[i].last_seen_tick) >
             ROUTER_NODE_TIMEOUT_MS))
        {
            memset(&g_nodes[i], 0, sizeof(g_nodes[i]));
            Router_Count(nodes_aged_out);
        }
    }

    for (i = 0U; i < ROUTER_MAX_ROUTES; i++)
    {
        if ((g_routes[i].used != 0U) &&
            ((g_routes[i].flags & ROUTER_ROUTE_FLAG_STATIC) == 0U) &&
            (Router_AgeMsFrom(
                 now,
                 g_routes[i].last_seen_tick) >
             ROUTER_ROUTE_TIMEOUT_MS))
        {
            memset(&g_routes[i], 0, sizeof(g_routes[i]));
            Router_Count(routes_aged_out);
        }
    }

    for (i = 0U; i < ROUTER_DUP_CACHE_SIZE; i++)
    {
        if ((g_dup_cache[i].used != 0U) &&
            (Router_AgeMsFrom(
                 now,
                 g_dup_cache[i].seen_tick) >
             ROUTER_DUP_WINDOW_MS))
        {
            memset(&g_dup_cache[i], 0, sizeof(g_dup_cache[i]));
        }
    }

    taskEXIT_CRITICAL();

    if (Router_AgeMsFrom(
            now,
            g_last_discovery_tick) >=
        ROUTER_DISCOVERY_INTERVAL_MS)
    {
        (void)Router_SendHello(NULL);
    }
}


uint8_t Router_LocalReadPacket(RouterPacket_t *out)
{
    if ((out == NULL) ||
        (g_local_queue == NULL))
    {
        return 0U;
    }

    if (xQueueReceive(
            g_local_queue,
            out,
            0U) != pdPASS)
    {
        return 0U;
    }

    return 1U;
}


uint8_t Router_LocalReadLine(char *out,
                             size_t out_size)
{
    RouterPacket_t packet;
    size_t len;

    if ((out == NULL) ||
        (out_size == 0U))
    {
        return 0U;
    }

    if (Router_LocalReadPacket(&packet) == 0U)
    {
        return 0U;
    }

    len = packet.length;

    if (len >= out_size)
    {
        len = out_size - 1U;
    }

    memcpy(out, packet.payload, len);
    out[len] = '\0';

    return 1U;
}


uint8_t Router_SendSpan(uint16_t dst, uint8_t type, const char *payload,
                        size_t length, uint16_t *out_seq)
{
    return Router_SendPacketSpan(dst, type, payload, length, out_seq);
}

uint8_t Router_SendText(uint16_t dst,
                        uint8_t type,
                        const char *payload,
                        uint16_t *out_seq)
{
    return Router_SendPacketSpan(
        dst,
        type,
        payload,
        payload != NULL ? strlen(payload) : 0U,
        out_seq);
}


void Router_GetStatus(RouterStatus_t *out)
{
    if (out == NULL)
    {
        return;
    }

    taskENTER_CRITICAL();
    *out = g_status;
    taskEXIT_CRITICAL();
}


uint32_t Router_GetNodeCount(void)
{
    uint32_t i;
    uint32_t count = 0U;

    taskENTER_CRITICAL();

    for (i = 0U; i < ROUTER_MAX_NODES; i++)
    {
        if (g_nodes[i].used != 0U)
        {
            count++;
        }
    }

    taskEXIT_CRITICAL();

    return count;
}


uint8_t Router_GetNode(uint32_t index,
                       RouterNodeInfo_t *out)
{
    uint32_t i;
    uint32_t seen = 0U;
    RouterNodeEntry_t entry;
    uint8_t found = 0U;

    if (out == NULL)
    {
        return 0U;
    }

    taskENTER_CRITICAL();

    for (i = 0U; i < ROUTER_MAX_NODES; i++)
    {
        if (g_nodes[i].used != 0U)
        {
            if (seen == index)
            {
                entry = g_nodes[i];
                found = 1U;
                break;
            }

            seen++;
        }
    }

    taskEXIT_CRITICAL();

    if (found == 0U)
    {
        return 0U;
    }

    out->node_id = entry.node_id;
    out->port = entry.port;
    out->flags = entry.flags;
    out->age_ms = Router_AgeMs(entry.last_seen_tick);
    out->rx_packets = entry.rx_packets;

    return 1U;
}


uint32_t Router_GetRouteCount(void)
{
    uint32_t i;
    uint32_t count = 0U;

    taskENTER_CRITICAL();

    for (i = 0U; i < ROUTER_MAX_ROUTES; i++)
    {
        if (g_routes[i].used != 0U)
        {
            count++;
        }
    }

    taskEXIT_CRITICAL();

    return count;
}


uint8_t Router_GetRoute(uint32_t index,
                        RouterRouteInfo_t *out)
{
    uint32_t i;
    uint32_t seen = 0U;
    RouterRouteEntry_t entry;
    uint8_t found = 0U;

    if (out == NULL)
    {
        return 0U;
    }

    taskENTER_CRITICAL();

    for (i = 0U; i < ROUTER_MAX_ROUTES; i++)
    {
        if (g_routes[i].used != 0U)
        {
            if (seen == index)
            {
                entry = g_routes[i];
                found = 1U;
                break;
            }

            seen++;
        }
    }

    taskEXIT_CRITICAL();

    if (found == 0U)
    {
        return 0U;
    }

    out->destination = entry.destination;
    out->port = entry.port;
    out->metric = entry.metric;
    out->flags = entry.flags;
    out->age_ms = Router_AgeMs(entry.last_seen_tick);

    return 1U;
}
