#ifndef ROUTER_RPC_WIRE_H
#define ROUTER_RPC_WIRE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Opt-in unary read-only RPC to STM32 node 1. 4 + 2*110 = 224 ASCII bytes.
 * No fragments, streams, legacy console, Flash writes, or authenticated ID. */
#define RN_RPC_TYPE 8U
#define RN_RPC_MAX_PACKET 110U
#define RN_RPC_CHANNEL_BASE 65536U
#define RN_RPC_SERVICE 0x45FA4BE2U
#define RN_RPC_PING 0x860C5B16U
#define RN_RPC_STATUS 0x87DEA601U
#define RN_RPC_PARAMS 0x9C8A06ADU
#define RN_RPC_DIAGNOSTICS 0x425E79C4U
typedef struct {
    uint32_t type, channel, service, method, call, status;
    const uint8_t *payload;
    size_t payload_size;
} rn_rpc_packet_t;
bool rn_rpc_decode(const uint8_t *data, size_t size, rn_rpc_packet_t *out);
size_t rn_rpc_unhex(const char *text, uint8_t *out, size_t capacity);
size_t rn_rpc_hex(const uint8_t *data, size_t size, char *out, size_t capacity);
bool rn_rpc_allowed(uint16_t src, uint16_t dst, const char *text);
#ifdef __cplusplus
}
#endif
#endif
