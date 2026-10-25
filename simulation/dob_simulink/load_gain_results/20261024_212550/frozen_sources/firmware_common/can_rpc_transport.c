#include "can_rpc_transport.h"
#include <string.h>

uint16_t CanRpc_Crc16(const uint8_t *data, size_t size)
{
    uint16_t crc = 0xFFFFU;
    for (size_t i = 0U; i < size; ++i) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (unsigned bit = 0U; bit < 8U; ++bit)
            crc = (uint16_t)((crc & 0x8000U) ? ((uint32_t)crc << 1) ^ 0x1021U
                                                    : (uint32_t)crc << 1);
    }
    return crc;
}
void CanRpc_Reset(CanRpcReceiver *receiver)
{
    if (receiver != NULL) memset(receiver, 0, sizeof(*receiver));
}
int CanRpc_Expire(CanRpcReceiver *r, uint32_t now)
{
    if (r != NULL && r->active &&
        ((uint32_t)(now - r->last_ms) >= CAN_RPC_IDLE_TIMEOUT_MS ||
         (uint32_t)(now - r->started_ms) >= CAN_RPC_PACKET_TIMEOUT_MS)) {
        r->active = 0U;
        return 1;
    }
    return 0;
}
size_t CanRpc_FrameCount(size_t length)
{
    return length != 0U && length <= CAN_RPC_MAX_PACKET
        ? 1U + (length + CAN_RPC_DATA_BYTES - 1U) / CAN_RPC_DATA_BYTES : 0U;
}
int CanRpc_EncodeFrame(const CanRpcPacket *p, size_t frame, uint8_t out[8])
{
    if (p == NULL || out == NULL || p->transaction == 0U ||
        frame >= CanRpc_FrameCount(p->length)) return 0;
    memset(out, 0, 8U);
    out[1] = (uint8_t)p->transaction; out[2] = (uint8_t)(p->transaction >> 8);
    if (frame == 0U) {
        const uint16_t crc = CanRpc_Crc16(p->bytes, p->length);
        out[0] = CAN_RPC_START; out[3] = (uint8_t)p->length;
        out[4] = (uint8_t)(p->length >> 8); out[5] = (uint8_t)crc;
        out[6] = (uint8_t)(crc >> 8); out[7] = 1U;
    } else {
        const size_t offset = (frame - 1U) * CAN_RPC_DATA_BYTES;
        size_t count = p->length - offset;
        if (count > CAN_RPC_DATA_BYTES) count = CAN_RPC_DATA_BYTES;
        out[0] = CAN_RPC_DATA; out[3] = (uint8_t)(frame - 1U);
        memcpy(out + 4U, p->bytes + offset, count);
    }
    return 1;
}
CanRpcResult CanRpc_Feed(CanRpcReceiver *r, uint32_t expected_id, uint32_t id,
    uint8_t extended, uint8_t remote, uint8_t error, uint8_t fd_format,
    uint8_t dlc, const uint8_t *d, uint32_t now)
{
    if (r == NULL) return CAN_RPC_INVALID;
    if (id != expected_id) return CAN_RPC_IGNORED;
    const int expired = CanRpc_Expire(r, now);
    if (d == NULL || extended || remote || error || fd_format || dlc != 8U) {
        r->active = 0U; return CAN_RPC_INVALID;
    }
    const uint16_t transaction = (uint16_t)(d[1] | ((uint16_t)d[2] << 8));
    if (transaction == 0U) { r->active = 0U; return CAN_RPC_INVALID; }
    if (d[0] == CAN_RPC_START) {
        const uint16_t length = (uint16_t)(d[3] | ((uint16_t)d[4] << 8));
        if (d[7] != 1U || length == 0U || length > CAN_RPC_MAX_PACKET) {
            r->active = 0U; return CAN_RPC_INVALID;
        }
        /* A repeated start cannot extend deadlines or replace another client. */
        if (r->active) return CAN_RPC_BUSY;
        if (r->completed_seen && transaction == r->completed_transaction &&
            (uint32_t)(now - r->completed_ms) < CAN_RPC_PACKET_TIMEOUT_MS)
            return CAN_RPC_IGNORED;
        r->packet.transaction = transaction; r->packet.length = length;
        r->crc = (uint16_t)(d[5] | ((uint16_t)d[6] << 8));
        r->received = 0U; r->next_index = 0U;
        r->started_ms = now; r->last_ms = now; r->active = 1U;
        return CAN_RPC_PARTIAL;
    }
    if (d[0] != CAN_RPC_DATA) { r->active = 0U; return CAN_RPC_INVALID; }
    if (!r->active) return expired ? CAN_RPC_TIMED_OUT : CAN_RPC_IGNORED;
    if (transaction != r->packet.transaction) return CAN_RPC_IGNORED;
    if (d[3] != r->next_index) { r->active = 0U; return CAN_RPC_INVALID; }
    size_t count = r->packet.length - r->received;
    if (count > CAN_RPC_DATA_BYTES) count = CAN_RPC_DATA_BYTES;
    for (size_t i = count; i < CAN_RPC_DATA_BYTES; ++i)
        if (d[4U + i] != 0U) { r->active = 0U; return CAN_RPC_INVALID; }
    memcpy(r->packet.bytes + r->received, d + 4U, count);
    r->received = (uint16_t)(r->received + count);
    ++r->next_index; r->last_ms = now;
    if (r->received != r->packet.length) return CAN_RPC_PARTIAL;
    r->active = 0U;
    if (CanRpc_Crc16(r->packet.bytes, r->packet.length) != r->crc)
        return CAN_RPC_BAD_CRC;
    r->completed_transaction = transaction; r->completed_ms = now;
    r->completed_seen = 1U;
    return CAN_RPC_COMPLETE;
}
