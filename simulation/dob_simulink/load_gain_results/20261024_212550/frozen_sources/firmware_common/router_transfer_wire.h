#ifndef ROUTER_TRANSFER_WIRE_H
#define ROUTER_TRANSFER_WIRE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Generic bounded binary transport. NOT an authorization to execute bytes.
 * R1 type 9 never enters the console. Forwarders do not decode pw_transfer. */
#define RN_TRANSFER_TYPE 9U
#define RN_TRANSFER_MAX_PACKET 1024U
#define RN_TRANSFER_FRAGMENT 88U
#define RN_TRANSFER_SLOTS 2U
#define RN_TRANSFER_TIMEOUT_MS 2000U
typedef struct {
    uint32_t id, crc;
    uint16_t offset, total, size;
    uint8_t data[RN_TRANSFER_FRAGMENT];
} rn_transfer_fragment_t;
typedef struct {
    uint8_t data[RN_TRANSFER_MAX_PACKET];
    uint32_t id, crc, epoch, started;
    uint16_t src, dst, total, bitmap;
    uint8_t port;
    bool used, held;
} rn_transfer_slot_t;
typedef struct {
    rn_transfer_slot_t slots[RN_TRANSFER_SLOTS];
    uint32_t rejected, expired, corrupt, completed;
} rn_transfer_receiver_t;
typedef struct {
    const uint8_t *data;
    uint16_t size;
    unsigned slot;
} rn_transfer_view_t;
typedef enum {
    RN_TRANSFER_REJECTED,
    RN_TRANSFER_PENDING,
    RN_TRANSFER_COMPLETE
} rn_transfer_result_t;
uint32_t rn_transfer_crc32(const uint8_t *data, size_t size);
bool rn_transfer_parse(const char *text, rn_transfer_fragment_t *out);
bool rn_transfer_allowed(uint16_t src, uint16_t dst, const char *text);
size_t rn_transfer_format(uint32_t id, const uint8_t *packet, size_t total, size_t offset,
                          char *out, size_t capacity);
/* Single owning task. Release the immutable view after ProcessPacket copies it.
 * Two fixed slots, no allocation. Duplicates/out-of-order allowed, CRC required. */
void rn_transfer_expire(rn_transfer_receiver_t *receiver, uint32_t now);
rn_transfer_result_t rn_transfer_feed(rn_transfer_receiver_t *receiver, uint16_t src, uint16_t dst,
                                      uint8_t port, uint32_t epoch, const char *text, uint32_t now,
                                      rn_transfer_view_t *view);
void rn_transfer_release(rn_transfer_receiver_t *receiver, unsigned slot);
#ifdef __cplusplus
}
#endif
#endif
