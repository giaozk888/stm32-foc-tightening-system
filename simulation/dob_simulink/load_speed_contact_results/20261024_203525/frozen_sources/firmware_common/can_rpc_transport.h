#ifndef CAN_RPC_TRANSPORT_H
#define CAN_RPC_TRANSPORT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* One trusted local client, classic CAN 500 kbit/s. Not authentication. */
#define CAN_RPC_REQUEST_ID 0x600U
#define CAN_RPC_REPLY_ID 0x601U
#define CAN_RPC_MAX_PACKET 128U
#define CAN_RPC_DATA_BYTES 4U
#define CAN_RPC_IDLE_TIMEOUT_MS 500U
#define CAN_RPC_PACKET_TIMEOUT_MS 5000U
#define CAN_RPC_START 0xA1U
#define CAN_RPC_DATA 0xA2U

typedef struct {
    uint16_t transaction;
    uint16_t length;
    uint8_t bytes[CAN_RPC_MAX_PACKET];
} CanRpcPacket;
typedef struct {
    CanRpcPacket packet;
    uint32_t started_ms, last_ms, completed_ms;
    uint16_t crc, received, completed_transaction;
    uint8_t next_index, active, completed_seen;
} CanRpcReceiver;
typedef enum {
    CAN_RPC_IGNORED = 0, CAN_RPC_PARTIAL, CAN_RPC_COMPLETE,
    CAN_RPC_INVALID, CAN_RPC_TIMED_OUT, CAN_RPC_BUSY, CAN_RPC_BAD_CRC
} CanRpcResult;

void CanRpc_Reset(CanRpcReceiver *receiver);
/* Clears a partial packet only. A completed packet remains valid until Feed. */
int CanRpc_Expire(CanRpcReceiver *receiver, uint32_t now_ms);
CanRpcResult CanRpc_Feed(CanRpcReceiver *receiver, uint32_t expected_id,
    uint32_t id, uint8_t extended, uint8_t remote, uint8_t error,
    uint8_t fd_format, uint8_t dlc, const uint8_t *data, uint32_t now_ms);
uint16_t CanRpc_Crc16(const uint8_t *data, size_t size);
/* Frame zero is START; subsequent frames carry four bytes and zero padding. */
size_t CanRpc_FrameCount(size_t packet_size);
int CanRpc_EncodeFrame(const CanRpcPacket *packet, size_t frame, uint8_t out[8]);
#ifdef __cplusplus
}
#endif
#endif
