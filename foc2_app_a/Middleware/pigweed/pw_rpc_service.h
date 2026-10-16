#ifndef PW_RPC_SERVICE_H
#define PW_RPC_SERVICE_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

void PW_Rpc_Init(void);
void PW_Rpc_HandleCommand(uint32_t request_id, const char *args);
void PW_Transfer_HandleCommand(uint32_t request_id, const char *args);
#if defined(CAN_RPC_READ_ONLY)
/* Init in StartupTask; Process/Tick in ProtocolTask. CAN has no write entry. */
int PW_Rpc_CanInit(void);
#if defined(PW_TRANSFER_HOST)
void PW_Rpc_CanTransferRun(void);
void PW_Rpc_CanTransferStop(void);
#endif
int PW_Rpc_CanProcess(uint16_t transaction, const uint8_t *packet, size_t size);
void PW_Rpc_CanTick(uint32_t now);
#endif

#ifdef __cplusplus
}
#endif

#endif
