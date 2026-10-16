#include "router.h"
#include "rpc_readonly.h"
#include "queue.h"
#include "task.h"
#include <assert.h>
#include <string.h>
static StaticQueue_t queues[2];
static uint8_t storage[2][8U*sizeof(RouterPacket_t)];
static unsigned created;
unsigned router_rpc_test_snapshot_calls;
TickType_t router_rpc_test_tick;
QueueHandle_t xQueueCreate(UBaseType_t depth,UBaseType_t size)
{
    assert(created < 2 && depth <= 8 && size == sizeof(RouterPacket_t));
    StaticQueue_t *q=&queues[created];
    *q=(StaticQueue_t){depth,size,0,0,storage[created++]}; return q;
}
BaseType_t xQueueSend(QueueHandle_t q,const void *item,TickType_t wait)
{
    (void)wait;
    if (q->count == q->depth) return pdFALSE;
    memcpy(q->storage+((q->head+q->count)%q->depth)*q->item_size,item,q->item_size);
    ++q->count; return pdPASS;
}
BaseType_t xQueueReceive(QueueHandle_t q,void *item,TickType_t wait)
{
    (void)wait; if (!q->count) return pdFALSE;
    memcpy(item,q->storage+q->head*q->item_size,q->item_size);
    q->head=(q->head+1U)%q->depth; --q->count; return pdPASS;
}
UBaseType_t uxQueueMessagesWaiting(QueueHandle_t q) { return q->count; }
TickType_t xTaskGetTickCount(void) { return router_rpc_test_tick; }
size_t PW_Rpc_ReadOnlySnapshot(uint32_t kind,uint8_t *out,size_t capacity)
{
    ++router_rpc_test_snapshot_calls;
    size_t count=kind == 1 ? 8 : kind == 2 ? 19 : 10;
    assert(capacity >= count*4);
    /* Deliberately synthetic business data; actual Server/Router are not mocked. */
    for (size_t i=0; i<count; ++i) {
        uint32_t value=i ? kind*100+(uint32_t)i : RPC_READONLY_VERSION;
        for (unsigned n=0; n<4; ++n) out[4*i+n]=(uint8_t)(value >> (8*n));
    }
    return count*4;
}
