#include "pw_log_router_bridge.h"

#include <stdio.h>
#include <string.h>

#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"

#include "pw_log_backend.h"
#include "uart_async.h"

#define PW_LOG_ROUTER_QUEUE_DEPTH 8U
#define PW_LOG_ROUTER_TEXT_MAX    192U

typedef struct
{
    uint8_t active;
    uint8_t min_level;
    uint16_t node_id;
    TickType_t expires_tick;
} PW_LogRouterSubscriberSlot_t;

typedef struct
{
    PwLogRef ref;
    uint16_t length;
} PW_LogRouterRecord_t;

static PW_LogRouterSubscriberSlot_t s_subscribers[PW_LOG_ROUTER_MAX_SUBSCRIBERS];
static StaticQueue_t s_queue_control;
static uint8_t s_queue_storage[PW_LOG_ROUTER_QUEUE_DEPTH * sizeof(PW_LogRouterRecord_t)];
static QueueHandle_t s_queue;
static volatile uint32_t s_ready;
static volatile uint32_t s_subscriber_count;
static volatile uint32_t s_captured;
static volatile uint32_t s_queue_dropped;
static volatile uint32_t s_routed_sent;
static volatile uint32_t s_route_failed;
static volatile uint32_t s_level_filtered;
static volatile uint32_t s_expired;
static volatile uint32_t s_remote_received;

static uint8_t PW_LogRouter_LevelValid(int level)
{
    return ((level >= PW_LOG_RUNTIME_DEBUG) &&
            (level <= PW_LOG_RUNTIME_CRITICAL)) ||
           (level == PW_LOG_RUNTIME_FATAL);
}

static void PW_LogRouter_Recount(void)
{
    uint32_t i;
    uint32_t count = 0U;
    for (i = 0U; i < PW_LOG_ROUTER_MAX_SUBSCRIBERS; i++)
    {
        if (s_subscribers[i].active != 0U)
        {
            count++;
        }
    }
    s_subscriber_count = count;
}

static void PW_LogRouter_Expire(TickType_t now)
{
    uint32_t i;
    uint8_t changed = 0U;
    for (i = 0U; i < PW_LOG_ROUTER_MAX_SUBSCRIBERS; i++)
    {
        if ((s_subscribers[i].active != 0U) &&
            ((int32_t)(now - s_subscribers[i].expires_tick) >= 0))
        {
            memset(&s_subscribers[i], 0, sizeof(s_subscribers[i]));
            s_expired++;
            changed = 1U;
        }
    }
    if (changed != 0U)
    {
        PW_LogRouter_Recount();
    }
}

static uint8_t PW_LogRouter_Capture(PwLogRef ref)
{
    PW_LogRouterRecord_t record;
    const PwLogRecord *view = PwLogStore_View(ref);
    const char *text = view != NULL ? view->text : NULL;
    size_t length = view != NULL ? view->length : 0U;

    if ((s_ready == 0U) || (s_subscriber_count == 0U))
    {
        return 1U;
    }
    if ((text == NULL) || (length == 0U))
    {
        return 0U;
    }

    while ((length > 0U) &&
           ((text[length - 1U] == '\r') || (text[length - 1U] == '\n')))
    {
        length--;
    }
    if (length > PW_LOG_ROUTER_TEXT_MAX)
    {
        length = PW_LOG_ROUTER_TEXT_MAX;
    }

    if (!PwLogStore_Retain(ref)) return 0U;
    record.ref = ref;
    record.length = (uint16_t)length;

    if (xQueueSend(s_queue, &record, 0U) != pdPASS)
    {
        (void)PwLogStore_Release(ref);
        s_queue_dropped++;
        return 0U;
    }
    s_captured++;
    return 1U;
}

int PW_LogRouter_Init(void)
{
    if (s_ready != 0U)
    {
        return 1;
    }
    memset(s_subscribers, 0, sizeof(s_subscribers));
    s_queue = xQueueCreateStatic(PW_LOG_ROUTER_QUEUE_DEPTH,
                                 sizeof(PW_LogRouterRecord_t),
                                 s_queue_storage,
                                 &s_queue_control);
    if (s_queue == NULL)
    {
        return 0;
    }
    PW_Log_SetSharedMirrorCallback(PW_LogRouter_Capture);
    s_ready = 1U;
    return 1;
}

int PW_LogRouter_Subscribe(uint16_t node_id, int min_level, uint32_t ttl_seconds)
{
    uint32_t i;
    int32_t free_index = -1;
    TickType_t now = xTaskGetTickCount();

    if ((s_ready == 0U) || (node_id == 0U) ||
        (node_id == ROUTER_BROADCAST_NODE) || (node_id == 1U) ||
        (PW_LogRouter_LevelValid(min_level) == 0U) ||
        (ttl_seconds == 0U) || (ttl_seconds > 3600U))
    {
        return 0;
    }

    PW_LogRouter_Expire(now);
    for (i = 0U; i < PW_LOG_ROUTER_MAX_SUBSCRIBERS; i++)
    {
        if ((s_subscribers[i].active != 0U) &&
            (s_subscribers[i].node_id == node_id))
        {
            free_index = (int32_t)i;
            break;
        }
        if ((free_index < 0) && (s_subscribers[i].active == 0U))
        {
            free_index = (int32_t)i;
        }
    }
    if (free_index < 0)
    {
        return 0;
    }

    s_subscribers[free_index].node_id = node_id;
    s_subscribers[free_index].min_level = (uint8_t)min_level;
    s_subscribers[free_index].expires_tick =
        now + pdMS_TO_TICKS(ttl_seconds * 1000U);
    s_subscribers[free_index].active = 1U;
    PW_LogRouter_Recount();
    return 1;
}

int PW_LogRouter_Unsubscribe(uint16_t node_id)
{
    uint32_t i;
    for (i = 0U; i < PW_LOG_ROUTER_MAX_SUBSCRIBERS; i++)
    {
        if ((s_subscribers[i].active != 0U) &&
            (s_subscribers[i].node_id == node_id))
        {
            memset(&s_subscribers[i], 0, sizeof(s_subscribers[i]));
            PW_LogRouter_Recount();
            return 1;
        }
    }
    return 0;
}

void PW_LogRouter_GetDiagnostics(PW_LogRouterDiagnostics_t *diagnostics)
{
    if (diagnostics == NULL)
    {
        return;
    }
    PW_LogRouter_Expire(xTaskGetTickCount());
    diagnostics->ready = s_ready;
    diagnostics->subscribers = s_subscriber_count;
    diagnostics->queued = (s_queue != NULL)
                              ? (uint32_t)uxQueueMessagesWaiting(s_queue)
                              : 0U;
    diagnostics->queue_capacity = PW_LOG_ROUTER_QUEUE_DEPTH;
    diagnostics->captured = s_captured;
    diagnostics->queue_dropped = s_queue_dropped;
    diagnostics->routed_sent = s_routed_sent;
    diagnostics->route_failed = s_route_failed;
    diagnostics->level_filtered = s_level_filtered;
    diagnostics->expired = s_expired;
    diagnostics->remote_received = s_remote_received;
}

int PW_LogRouter_GetSubscriber(uint32_t index, PW_LogRouterSubscriber_t *subscriber)
{
    uint32_t i;
    uint32_t current = 0U;
    TickType_t now = xTaskGetTickCount();

    if (subscriber == NULL)
    {
        return 0;
    }
    PW_LogRouter_Expire(now);
    for (i = 0U; i < PW_LOG_ROUTER_MAX_SUBSCRIBERS; i++)
    {
        if (s_subscribers[i].active == 0U)
        {
            continue;
        }
        if (current == index)
        {
            subscriber->node_id = s_subscribers[i].node_id;
            subscriber->min_level = s_subscribers[i].min_level;
            subscriber->remaining_ms =
                (uint32_t)(s_subscribers[i].expires_tick - now) * portTICK_PERIOD_MS;
            return 1;
        }
        current++;
    }
    return 0;
}

void PW_LogRouter_Service(uint32_t budget)
{
    PW_LogRouterRecord_t record;
    TickType_t now = xTaskGetTickCount();

    PW_LogRouter_Expire(now);
    while ((budget > 0U) && (s_queue != NULL) &&
           (xQueueReceive(s_queue, &record, 0U) == pdPASS))
    {
        uint32_t i;
        const PwLogRecord *view = PwLogStore_View(record.ref);
        if (view == NULL) { (void)PwLogStore_Release(record.ref); budget--; continue; }
        for (i = 0U; i < PW_LOG_ROUTER_MAX_SUBSCRIBERS; i++)
        {
            uint16_t seq = 0U;
            if (s_subscribers[i].active == 0U)
            {
                continue;
            }
            if (view->level < s_subscribers[i].min_level)
            {
                s_level_filtered++;
                continue;
            }
            if (Router_SendSpan(s_subscribers[i].node_id,
                                PW_LOG_ROUTER_PACKET_TYPE,
                                view->text,
                                record.length,
                                &seq) != 0U)
            {
                s_routed_sent++;
            }
            else
            {
                s_route_failed++;
            }
        }
        (void)PwLogStore_Release(record.ref);
        budget--;
    }
}

void PW_LogRouter_HandleRemote(const RouterPacket_t *packet)
{
    UART_AsyncTxLease_t lease = {0};
    size_t capacity;
    int n;
    if ((packet == NULL) || (packet->type != PW_LOG_ROUTER_PACKET_TYPE) ||
        packet->length > ROUTER_MAX_PAYLOAD)
    {
        return;
    }
    capacity = 48U + packet->length + 2U;
    if (!UART_Async_Acquire(capacity, 100U, &lease)) return;
    n = snprintf((char *)lease.data, capacity, "REMOTE LOG SRC=%u ",
                 (unsigned int)packet->src);
    if (n <= 0 || (size_t)n + packet->length + 2U > capacity) {
        (void)UART_Async_Cancel(&lease); return;
    }
    /* Router-owned packet representation -> final wire frame generation.
     * Not a shared log-store record, so its payload is still read/copied here. */
    memcpy(lease.data + n, packet->payload, packet->length);
    lease.data[n + packet->length] = '\r';
    lease.data[n + packet->length + 1U] = '\n';
    if (!UART_Async_Commit(&lease, (size_t)n + packet->length + 2U))
        (void)UART_Async_Cancel(&lease);
    s_remote_received++;
}
