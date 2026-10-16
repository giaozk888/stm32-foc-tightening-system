#ifndef PW_CAN_RPC_H
#define PW_CAN_RPC_H
#include "can_rpc_transport.h"
#include "can_status_tx.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    uint32_t received, complete, invalid, crc_errors, timeouts, busy;
    uint32_t request_dropped, rejected, response_dropped, response_enqueued;
    uint32_t fifo_overruns;
} PW_CanRpcDiagnostics;
int PW_CanRpc_Init(void); /* StartupTask, before MonitorTask starts. */
/* MonitorTask only; a FIFO overrun/recovery invalidates the entire partial packet. */
void PW_CanRpc_ResetLink(uint8_t overrun);
void PW_CanRpc_Receive(uint32_t id, uint8_t extended, uint8_t remote,
    uint8_t fd_format, uint8_t dlc, const uint8_t data[8], uint32_t now_ms);
void PW_CanRpc_MonitorService(uint32_t now_ms);
/* ProtocolTask owns incoming packets; global RPC mutex protects TransferThread. */
void PW_CanRpc_ProtocolService(void);
int PW_CanRpc_SubmitResponse(uint16_t transaction, const uint8_t *data, size_t size);
/* Asynchronous official TransferThread output: explicit originating link epoch. */
uint32_t PW_CanRpc_LinkEpoch(void);
int PW_CanRpc_SubmitStreamResponse(uint16_t transaction, uint32_t epoch,
    const uint8_t *data, size_t size);
void PW_CanRpc_GetDiagnostics(PW_CanRpcDiagnostics *out);
void PW_CanRpc_GetCanSnapshot(CAN_StatusTx_Health *out);
#ifdef __cplusplus
}
#endif
#endif
