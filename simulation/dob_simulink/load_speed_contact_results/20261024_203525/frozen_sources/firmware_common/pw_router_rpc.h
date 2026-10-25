#ifndef PW_ROUTER_RPC_H
#define PW_ROUTER_RPC_H
#include "router.h"
#include "router_rpc_wire.h"
#ifdef __cplusplus
extern "C" {
#endif
/* ProtocolTask only; synchronous unary methods. Never pass to old console.
 * Each of four static channels owns its reply destination. Returns accepted. */
int PW_RouterRpc_Process(const RouterPacket_t *packet, uint32_t now_ms);
#ifdef __cplusplus
}
#endif
#endif
