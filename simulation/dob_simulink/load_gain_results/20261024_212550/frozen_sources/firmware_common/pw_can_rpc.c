#include "pw_can_rpc.h"
#include "pw_rpc_service.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include <string.h>

#define RPC_QUEUE_DEPTH 4U
/* 128 B -> START + 32 DATA frames; at 100 ms/frame this needs 3.3 s. */
#define RPC_RESPONSE_TIMEOUT_MS 4000U
static StaticQueue_t s_rx_control, s_tx_control;
typedef struct { CanRpcPacket packet; uint32_t epoch; } RpcRequest;
static uint8_t s_rx_storage[RPC_QUEUE_DEPTH * sizeof(RpcRequest)];
static uint8_t s_tx_storage[RPC_QUEUE_DEPTH * sizeof(CanRpcPacket)];
static QueueHandle_t s_rx_queue, s_tx_queue;
static CanRpcReceiver s_receiver;
static CanRpcPacket s_tx;
static size_t s_tx_frame;
static uint32_t s_tx_started;
static uint8_t s_tx_active;
static PW_CanRpcDiagnostics s_diag;
static CAN_StatusTx_Health s_can_snapshot;
/* ProtocolTask owns this scratch packet (not its relatively small task stack). */
static RpcRequest s_protocol_request;
static uint32_t s_link_epoch, s_protocol_epoch;
static void increment(uint32_t *counter)
{
    taskENTER_CRITICAL(); ++*counter; taskEXIT_CRITICAL();
}
int PW_CanRpc_Init(void)
{
    if (s_rx_queue != NULL && s_tx_queue != NULL) return PW_Rpc_CanInit();
    CanRpc_Reset(&s_receiver);
    s_rx_queue = xQueueCreateStatic(RPC_QUEUE_DEPTH, sizeof(RpcRequest), s_rx_storage, &s_rx_control);
    s_tx_queue = xQueueCreateStatic(RPC_QUEUE_DEPTH, sizeof(CanRpcPacket), s_tx_storage, &s_tx_control);
    return s_rx_queue != NULL && s_tx_queue != NULL && PW_Rpc_CanInit();
}
void PW_CanRpc_ResetLink(uint8_t overrun)
{
    taskENTER_CRITICAL(); ++s_link_epoch; taskEXIT_CRITICAL();
    CanRpc_Reset(&s_receiver);
    if (overrun) increment(&s_diag.fifo_overruns);
    if (s_tx_active) { increment(&s_diag.response_dropped); s_tx_active = 0U; }
    /* Existing queued replies are dropped too; they belong to the old link. */
    while (s_tx_queue != NULL && xQueueReceive(s_tx_queue, &s_tx, 0U) == pdTRUE)
        increment(&s_diag.response_dropped);
    RpcRequest discarded;
    while (s_rx_queue != NULL && xQueueReceive(s_rx_queue, &discarded, 0U) == pdTRUE)
        increment(&s_diag.request_dropped);
}
void PW_CanRpc_Receive(uint32_t id, uint8_t extended, uint8_t remote,
    uint8_t fd, uint8_t dlc, const uint8_t data[8], uint32_t now)
{
    if (s_rx_queue == NULL) return;
    if (CanRpc_Expire(&s_receiver, now)) increment(&s_diag.timeouts);
    increment(&s_diag.received);
    const CanRpcResult result = CanRpc_Feed(&s_receiver, CAN_RPC_REQUEST_ID,
        id, extended, remote, 0U, fd, dlc, data, now);
    if (result == CAN_RPC_COMPLETE) {
        increment(&s_diag.complete);
        const RpcRequest request = {s_receiver.packet, s_link_epoch};
        if (xQueueSend(s_rx_queue, &request, 0U) != pdPASS)
            increment(&s_diag.request_dropped);
    } else if (result == CAN_RPC_BAD_CRC) increment(&s_diag.crc_errors);
    else if (result == CAN_RPC_INVALID) increment(&s_diag.invalid);
    else if (result == CAN_RPC_BUSY) increment(&s_diag.busy);
}
uint32_t PW_CanRpc_LinkEpoch(void)
{
    uint32_t epoch; taskENTER_CRITICAL(); epoch = s_link_epoch; taskEXIT_CRITICAL(); return epoch;
}
int PW_CanRpc_SubmitStreamResponse(uint16_t transaction, uint32_t epoch, const uint8_t *data, size_t size)
{
    CanRpcPacket response;
    if (s_tx_queue == NULL || data == NULL || transaction == 0U ||
        size == 0U || size > CAN_RPC_MAX_PACKET) return 0;
    response.transaction = transaction; response.length = (uint16_t)size;
    memcpy(response.bytes, data, size);
    /* Atomically check and enqueue: recovery cannot insert an old response
     * after the old queues have been drained. The copy is bounded to 132 B. */
    taskENTER_CRITICAL();
    const int current = epoch == s_link_epoch;
    const BaseType_t queued = current ? xQueueSend(s_tx_queue, &response, 0U) : pdFALSE;
    taskEXIT_CRITICAL();
    if (queued != pdPASS) {
        increment(&s_diag.response_dropped); return 0;
    }
    increment(&s_diag.response_enqueued); return 1;
}
int PW_CanRpc_SubmitResponse(uint16_t transaction, const uint8_t *data, size_t size)
{
    return PW_CanRpc_SubmitStreamResponse(transaction, s_protocol_epoch, data, size);
}
void PW_CanRpc_ProtocolService(void)
{
    PW_Rpc_CanTick((uint32_t)xTaskGetTickCount());
    /* One bounded packet per 5 ms tick; reads, Transfer.Read, and optionally
     * MotorControl (production adapter always rejects remote actions). */
    if (s_rx_queue != NULL && xQueueReceive(s_rx_queue, &s_protocol_request, 0U) == pdTRUE) {
        s_protocol_epoch = s_protocol_request.epoch;
        taskENTER_CRITICAL();
        const int current = s_protocol_epoch == s_link_epoch;
        taskEXIT_CRITICAL();
        if (!current) { increment(&s_diag.request_dropped); return; }
        if (!PW_Rpc_CanProcess(s_protocol_request.packet.transaction,
                s_protocol_request.packet.bytes, s_protocol_request.packet.length)) increment(&s_diag.rejected);
    }
}
void PW_CanRpc_MonitorService(uint32_t now)
{
    CAN_StatusTx_Health snapshot;
    CAN_StatusTx_GetHealth(&snapshot);
    taskENTER_CRITICAL(); s_can_snapshot = snapshot; taskEXIT_CRITICAL();
    if (CanRpc_Expire(&s_receiver, now)) increment(&s_diag.timeouts);
    if (!snapshot.ready || snapshot.recovery_exhausted) return;
    if (!s_tx_active && s_tx_queue != NULL && xQueueReceive(s_tx_queue, &s_tx, 0U) == pdTRUE) {
        s_tx_frame = 0U; s_tx_started = now; s_tx_active = 1U;
    }
    if (!s_tx_active) return;
    if ((uint32_t)(now - s_tx_started) >= RPC_RESPONSE_TIMEOUT_MS) {
        increment(&s_diag.response_dropped); s_tx_active = 0U; return;
    }
    /* One frame/100 ms after telemetry: leave capacity for the live log mirror
     * too, in addition to the hardware slot reserved by TryRpcFrame. */
    for (unsigned budget = 0U; budget < 1U; ++budget) {
        uint8_t frame[8];
        if (!CanRpc_EncodeFrame(&s_tx, s_tx_frame, frame)) {
            increment(&s_diag.response_dropped); s_tx_active = 0U; return;
        }
        if (!CAN_StatusTx_TryRpcFrame(CAN_RPC_REPLY_ID, frame)) return;
        if (++s_tx_frame == CanRpc_FrameCount(s_tx.length)) { s_tx_active = 0U; return; }
    }
}
void PW_CanRpc_GetDiagnostics(PW_CanRpcDiagnostics *out)
{
    if (out == NULL) return;
    taskENTER_CRITICAL(); *out = s_diag; taskEXIT_CRITICAL();
}
void PW_CanRpc_GetCanSnapshot(CAN_StatusTx_Health *out)
{
    if (out == NULL) return;
    taskENTER_CRITICAL(); *out = s_can_snapshot; taskEXIT_CRITICAL();
}
