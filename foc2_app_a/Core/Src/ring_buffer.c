#include "ring_buffer.h"

void RingBuffer_Init(RingBuffer_t *rb,
                     uint8_t *storage,
                     size_t capacity)
{
    if (rb == NULL)
    {
        return;
    }

    rb->buffer = storage;
    rb->capacity = capacity;
    rb->head = 0U;
    rb->tail = 0U;
}


size_t RingBuffer_Count(const RingBuffer_t *rb)
{
    size_t head;
    size_t tail;

    if ((rb == NULL) ||
        (rb->buffer == NULL) ||
        (rb->capacity < 2U))
    {
        return 0U;
    }

    head = rb->head;
    tail = rb->tail;

    if (head >= tail)
    {
        return head - tail;
    }

    return rb->capacity - (tail - head);
}


size_t RingBuffer_Free(const RingBuffer_t *rb)
{
    if ((rb == NULL) ||
        (rb->buffer == NULL) ||
        (rb->capacity < 2U))
    {
        return 0U;
    }

    return (rb->capacity - 1U) - RingBuffer_Count(rb);
}


size_t RingBuffer_Write(RingBuffer_t *rb,
                        const uint8_t *data,
                        size_t len)
{
    size_t written = 0U;

    if ((rb == NULL) ||
        (rb->buffer == NULL) ||
        (rb->capacity < 2U) ||
        (data == NULL))
    {
        return 0U;
    }

    while ((written < len) &&
           (RingBuffer_Free(rb) > 0U))
    {
        rb->buffer[rb->head] = data[written];

        rb->head++;
        if (rb->head >= rb->capacity)
        {
            rb->head = 0U;
        }

        written++;
    }

    return written;
}



size_t RingBuffer_Read(RingBuffer_t *rb,
                       uint8_t *dst,
                       size_t max_len)
{
    size_t read_count = 0U;

    if ((rb == NULL) ||
        (rb->buffer == NULL) ||
        (rb->capacity < 2U) ||
        (dst == NULL))
    {
        return 0U;
    }

    while ((read_count < max_len) &&
           (RingBuffer_Count(rb) > 0U))
    {
        dst[read_count] = rb->buffer[rb->tail];

        rb->tail++;
        if (rb->tail >= rb->capacity)
        {
            rb->tail = 0U;
        }

        read_count++;
    }

    return read_count;
}


size_t RingBuffer_PeekContiguous(const RingBuffer_t *rb,
                                 const uint8_t **ptr)
{
    size_t head;
    size_t tail;

    if (ptr != NULL)
    {
        *ptr = NULL;
    }

    if ((rb == NULL) ||
        (rb->buffer == NULL) ||
        (rb->capacity < 2U) ||
        (ptr == NULL))
    {
        return 0U;
    }

    head = rb->head;
    tail = rb->tail;

    if (head == tail)
    {
        return 0U;
    }

    *ptr = &rb->buffer[tail];

    if (head > tail)
    {
        return head - tail;
    }

    return rb->capacity - tail;
}


void RingBuffer_Consume(RingBuffer_t *rb, size_t len)
{
    size_t count;

    if ((rb == NULL) ||
        (rb->buffer == NULL) ||
        (rb->capacity < 2U))
    {
        return;
    }

    count = RingBuffer_Count(rb);
    if (len > count)
    {
        len = count;
    }

    rb->tail = (rb->tail + len) % rb->capacity;
}
