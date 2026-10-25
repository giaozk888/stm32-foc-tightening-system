#ifndef RPC_READONLY_H
#define RPC_READONLY_H
#include <stddef.h>
#include <stdint.h>
#define RPC_READONLY_VERSION 1U
#define RPC_READONLY_STATUS_WORDS 8U
#define RPC_READONLY_DIAG_WORDS 10U
#define RPC_READONLY_PARAMS_WORDS 19U
#define RPC_READONLY_PAYLOAD_MAX (RPC_READONLY_PARAMS_WORDS * 4U)
#define RPC_READONLY_SNAPSHOT_STATUS 1U
#define RPC_READONLY_SNAPSHOT_PARAMS 2U
#define RPC_READONLY_SNAPSHOT_DIAGNOSTICS 3U
#ifdef __cplusplus
extern "C" {
#endif
/* Read-only snapshot provider. No actuator, Flash-write, reset or HAL CAN API. */
size_t PW_Rpc_ReadOnlySnapshot(uint32_t method, uint8_t *out, size_t capacity);
#ifdef __cplusplus
}
#endif
#endif
