#ifndef ROUTER_H
#define ROUTER_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>
#include <stdint.h>

#define ROUTER_MAX_PAYLOAD             224U
#define ROUTER_MAX_NODES                 8U
#define ROUTER_MAX_ROUTES                8U
#define ROUTER_RX_QUEUE_DEPTH            8U
#define ROUTER_LOCAL_QUEUE_DEPTH         8U
#define ROUTER_DUP_CACHE_SIZE           16U

#define ROUTER_BROADCAST_NODE        0xFFFFU
#define ROUTER_DEFAULT_TTL                8U

/*
 * Stage 2 dynamic-router timing.
 *
 * Every active router sends a broadcast HELLO periodically.
 * A learned node/route must be refreshed by traffic before the timeout,
 * otherwise it is aged out automatically.
 */
#define ROUTER_DISCOVERY_INTERVAL_MS   5000U
#define ROUTER_NODE_TIMEOUT_MS        15000U
#define ROUTER_ROUTE_TIMEOUT_MS       15000U
#define ROUTER_DUP_WINDOW_MS          30000U
#define ROUTER_MAINTENANCE_PERIOD_MS    250U

typedef enum
{
    ROUTER_PORT_LOCAL  = 0,
    ROUTER_PORT_UART1  = 1,
    ROUTER_PORT_USB    = 2,
    ROUTER_PORT_SOCKET = 3,
    ROUTER_PORT_ESP32  = 4,
    ROUTER_PORT_COUNT
} RouterPort_t;

typedef enum
{
    ROUTER_PKT_PROTOCOL  = 1,
    ROUTER_PKT_TEXT      = 2,
    ROUTER_PKT_DISCOVERY = 3
} RouterPacketType_t;

#define ROUTER_DISCOVERY_HELLO_TEXT     "HELLO"
#define ROUTER_DISCOVERY_ANNOUNCE_TEXT  "ANNOUNCE"

#define ROUTER_NODE_FLAG_LOCAL       0x01U
#define ROUTER_NODE_FLAG_STATIC      0x02U
#define ROUTER_NODE_FLAG_LEARNED     0x04U
#define ROUTER_NODE_FLAG_DISCOVERED  0x08U

#define ROUTER_ROUTE_FLAG_STATIC     0x01U
#define ROUTER_ROUTE_FLAG_LEARNED    0x02U
#define ROUTER_ROUTE_FLAG_DISCOVERY  0x04U

typedef struct
{
    uint16_t src;
    uint16_t dst;
    uint16_t seq;
    uint8_t  type;
    uint8_t  ttl;
    uint16_t length;
    RouterPort_t ingress_port;
#if defined(ROUTER_READ_ONLY_NETWORK)
    uint32_t ingress_epoch; /* Internal only; never encoded into the R1 wire. */
#endif
    char payload[ROUTER_MAX_PAYLOAD + 1U];
} RouterPacket_t;

typedef struct
{
    uint16_t node_id;
    RouterPort_t port;
    uint8_t flags;
    uint32_t age_ms;
    uint32_t rx_packets;
} RouterNodeInfo_t;

typedef struct
{
    uint16_t destination;
    RouterPort_t port;
    uint8_t metric;
    uint8_t flags;
    uint32_t age_ms;
} RouterRouteInfo_t;

typedef struct
{
    uint16_t local_node_id;

    uint32_t rx_packets;
    uint32_t local_delivered;
    uint32_t forwarded;
    uint32_t tx_packets;

    uint32_t discovery_rx;
    uint32_t discovery_tx;

    uint32_t dropped_no_route;
    uint32_t dropped_ttl;
    uint32_t dropped_duplicate;
    uint32_t dropped_self_loop;
    uint32_t parse_errors;
    uint32_t rx_queue_full;
    uint32_t local_queue_full;

    uint32_t nodes_aged_out;
    uint32_t routes_aged_out;
} RouterStatus_t;

/* Return 1 on successful transport TX, 0 on failure. */
typedef uint8_t (*RouterPortTxFn)(const RouterPacket_t *packet);

uint8_t Router_Init(uint16_t local_node_id);
void Router_RegisterPortTx(RouterPort_t port, RouterPortTxFn tx_fn);

/* UART / USB / Socket adapters feed complete ASCII lines to the router. */
uint8_t Router_SubmitAsciiLine(RouterPort_t ingress_port, const char *line);

/* Drain queued ingress packets. max_packets=0 drains the queue. */
void Router_Service(uint32_t max_packets);

/*
 * Run periodic HELLO, route/node aging and duplicate-cache cleanup.
 * Safe to call every RouterTask iteration; internal period limiting is used.
 */
void Router_Maintenance(void);

/* Trigger one HELLO broadcast immediately. */
uint8_t Router_SendHello(uint16_t *out_seq);

/* Remove learned/dynamic nodes and routes; keep local/static state. */
void Router_ClearDynamic(void);
#if defined(ROUTER_READ_ONLY_NETWORK)
/* Called by the owning Router task on link disconnect; keep static routes. */
void Router_ForgetPort(RouterPort_t port);
/* Read-only link generation for asynchronous Transfer replies. */
uint32_t Router_PortEpoch(RouterPort_t port);
#endif

/* Nonblocking local endpoint receive. */
uint8_t Router_LocalReadPacket(RouterPacket_t *out);
uint8_t Router_LocalReadLine(char *out, size_t out_size);

/* Local endpoint transmit through the route table. */
uint8_t Router_SendText(uint16_t dst,
                        uint8_t type,
                        const char *payload,
                        uint16_t *out_seq);
/* Synchronous encoding/owned Router packet copy; caller keeps the span alive
 * for this call only. Allows trimming CRLF without a second text buffer. */
uint8_t Router_SendSpan(uint16_t dst, uint8_t type, const char *payload,
                        size_t length, uint16_t *out_seq);

/* ASCII transport framing. No CR/LF appended here. */
size_t Router_EncodeAsciiFrame(const RouterPacket_t *packet,
                               char *out,
                               size_t out_size);

void Router_GetStatus(RouterStatus_t *out);
uint32_t Router_GetNodeCount(void);
uint8_t Router_GetNode(uint32_t index, RouterNodeInfo_t *out);
uint32_t Router_GetRouteCount(void);
uint8_t Router_GetRoute(uint32_t index, RouterRouteInfo_t *out);
const char *Router_PortName(RouterPort_t port);

#ifdef __cplusplus
}
#endif

#endif /* ROUTER_H */
