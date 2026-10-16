#ifndef PW_LOG_ROUTER_BRIDGE_H
#define PW_LOG_ROUTER_BRIDGE_H

#include <stdint.h>

#include "router.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PW_LOG_ROUTER_PACKET_TYPE       6U
#define PW_LOG_ROUTER_MAX_SUBSCRIBERS   4U

typedef struct
{
    uint32_t ready;
    uint32_t subscribers;
    uint32_t queued;
    uint32_t queue_capacity;
    uint32_t captured;
    uint32_t queue_dropped;
    uint32_t routed_sent;
    uint32_t route_failed;
    uint32_t level_filtered;
    uint32_t expired;
    uint32_t remote_received;
} PW_LogRouterDiagnostics_t;

typedef struct
{
    uint16_t node_id;
    uint8_t min_level;
    uint32_t remaining_ms;
} PW_LogRouterSubscriber_t;

int PW_LogRouter_Init(void);
int PW_LogRouter_Subscribe(uint16_t node_id, int min_level, uint32_t ttl_seconds);
int PW_LogRouter_Unsubscribe(uint16_t node_id);
void PW_LogRouter_GetDiagnostics(PW_LogRouterDiagnostics_t *diagnostics);
int PW_LogRouter_GetSubscriber(uint32_t index, PW_LogRouterSubscriber_t *subscriber);
void PW_LogRouter_Service(uint32_t budget);
void PW_LogRouter_HandleRemote(const RouterPacket_t *packet);

#ifdef __cplusplus
}
#endif

#endif
