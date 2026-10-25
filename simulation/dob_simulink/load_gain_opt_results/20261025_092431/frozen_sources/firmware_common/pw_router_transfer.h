#ifndef PW_ROUTER_TRANSFER_H
#define PW_ROUTER_TRANSFER_H
#include "router.h"
#include "router_transfer_wire.h"
#ifdef __cplusplus
extern "C" {
#endif
#define RN_TRANSFER_CHANNEL_BASE 131072U
/* ProtocolTask only. Generic transport; this endpoint registers only Read/history.
 * Official TransferThread owns handler refs and state machine. No Flash/console path. */
void PW_RouterTransfer_Tick(uint32_t now_ms);
int PW_RouterTransfer_Process(const RouterPacket_t *packet, uint32_t now_ms);
/* Foreground diagnostic; zero until the worker starts. No private TCB access. */
uint32_t PW_RouterTransfer_StackFreeBytes(void);
#if defined(PW_TRANSFER_HOST)
void PW_RouterTransfer_Run(void);
void PW_RouterTransfer_Stop(void);
#endif
#ifdef __cplusplus
}
#endif
#endif
