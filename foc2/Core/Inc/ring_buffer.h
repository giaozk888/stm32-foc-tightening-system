#ifndef RING_BUFFER_H
#define RING_BUFFER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Generic byte ring buffer.
 *
 * Synchronization is deliberately NOT built into this module.
 * The owner decides how producers/consumers are serialized.
 *
 * One byte is intentionally left unused so head == tail unambiguously means
 * "empty".
 */
typedef struct
{
    uint8_t *buffer;
    size_t capacity;
    volatile size_t head;
    volatile size_t tail;
} RingBuffer_t;

void RingBuffer_Init(RingBuffer_t *rb,
                     uint8_t *storage,
                     size_t capacity);

size_t RingBuffer_Count(const RingBuffer_t *rb);
size_t RingBuffer_Free(const RingBuffer_t *rb);

/* Writes up to len bytes and returns bytes actually written. */
size_t RingBuffer_Write(RingBuffer_t *rb,
                        const uint8_t *data,
                        size_t len);

/* Reads up to max_len bytes and returns bytes actually read. */
size_t RingBuffer_Read(RingBuffer_t *rb,
                       uint8_t *dst,
                       size_t max_len);

/*
 * Returns the number of readable bytes that are contiguous from the current
 * tail to either head or the physical end of the storage.
 * *ptr receives a direct pointer into the ring storage.
 */
size_t RingBuffer_PeekContiguous(const RingBuffer_t *rb,
                                 const uint8_t **ptr);

/* Removes up to len bytes from the readable side. */
void RingBuffer_Consume(RingBuffer_t *rb, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* RING_BUFFER_H */
