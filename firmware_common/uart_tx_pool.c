#include "uart_tx_pool.h"

#include <stdatomic.h>
#include <limits.h>

_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "32-bit atomics must be lock-free");
_Static_assert(sizeof(unsigned int) == sizeof(uint32_t), "32-bit unsigned required");
_Static_assert(UART_TX_POOL_BLOCKS == 32U, "one bitmap word required");

enum { FREE = 0U, WRITING = 1U, QUEUED = 2U, IN_FLIGHT = 3U };
typedef struct {
    atomic_uint control; /* generation in upper bits; state in low two */
    uint32_t blocks;
    uint32_t length;
    uint32_t next; /* 0 = null; otherwise block index + 1 */
    const uint8_t *data;
    UartTxReleaseFn release;
    uint32_t context;
} Slot;

_Alignas(4) static uint8_t s_storage[UART_TX_POOL_BYTES];
static Slot s_slots[UART_TX_POOL_BLOCKS];
static atomic_uint s_reserved;
static atomic_uint s_ready_head;
static atomic_uint s_pending_bytes;
/* Only the TX consumer accesses the detached list and active token. */
static uint32_t s_batch;
static uint32_t s_active;

static uint32_t Mask(uint32_t start, uint32_t blocks)
{
    return (blocks == 32U) ? UINT32_MAX : (((1U << blocks) - 1U) << start);
}

void UartTxPool_Init(void)
{
    uint32_t i;
    atomic_init(&s_reserved, 0U);
    atomic_init(&s_ready_head, 0U);
    atomic_init(&s_pending_bytes, 0U);
    s_batch = 0U;
    s_active = 0U;
    for (i = 0U; i < UART_TX_POOL_BLOCKS; ++i) {
        atomic_init(&s_slots[i].control, FREE);
        s_slots[i].blocks = 0U;
        s_slots[i].length = 0U;
        s_slots[i].next = 0U;
    }
}

int UartTxPool_Acquire(size_t minimum_capacity, UartTxLease *out)
{
    uint32_t blocks;
    unsigned int bitmap;
    if ((out == NULL) || (minimum_capacity == 0U) ||
        (minimum_capacity > UART_TX_POOL_BYTES)) return 0;
    blocks = (uint32_t)((minimum_capacity + UART_TX_POOL_BLOCK_BYTES - 1U) /
                        UART_TX_POOL_BLOCK_BYTES);
    bitmap = atomic_load_explicit(&s_reserved, memory_order_relaxed);
    for (;;) {
        uint32_t start;
        int retry = 0;
        for (start = 0U; start + blocks <= UART_TX_POOL_BLOCKS; ++start) {
            uint32_t mask = Mask(start, blocks);
            if ((bitmap & mask) != 0U) continue;
            if (atomic_compare_exchange_weak_explicit(
                    &s_reserved, &bitmap, bitmap | mask,
                    memory_order_acquire, memory_order_relaxed)) {
                Slot *slot = &s_slots[start];
                unsigned int old = atomic_load_explicit(&slot->control,
                                                        memory_order_relaxed);
                unsigned int token = ((old & ~3U) + 4U) | WRITING;
                /* Bitmap ownership makes this slot exclusive until release. */
                slot->blocks = blocks;
                slot->length = 0U;
                slot->next = 0U;
                slot->data = &s_storage[start * UART_TX_POOL_BLOCK_BYTES];
                slot->release = NULL;
                slot->context = 0U;
                atomic_store_explicit(&slot->control, token, memory_order_release);
                out->data = &s_storage[start * UART_TX_POOL_BLOCK_BYTES];
                out->capacity = blocks * UART_TX_POOL_BLOCK_BYTES;
                out->block = start;
                out->token = token;
                return 1;
            }
            retry = 1;
            break; /* Another producer/consumer changed the bitmap: rescan. */
        }
        if (retry == 0) return 0;
    }
}

static int LeaseValid(const UartTxLease *lease)
{
    return (lease != NULL) && (lease->block < UART_TX_POOL_BLOCKS) &&
           (lease->data == &s_storage[lease->block * UART_TX_POOL_BLOCK_BYTES]) &&
           ((lease->token & 3U) == WRITING);
}

static void ClearLease(UartTxLease *lease)
{
    lease->data = NULL;
    lease->capacity = 0U;
    lease->token = 0U;
}

static int CommitPayload(UartTxLease *lease, const uint8_t *data, size_t length,
                         UartTxReleaseFn release, uint32_t context)
{
    Slot *slot;
    unsigned int expected;
    unsigned int head;
    if (!LeaseValid(lease) || data == NULL || length == 0U ||
        length > UART_TX_POOL_BYTES || (release == NULL && length > lease->capacity)) return 0;
    slot = &s_slots[lease->block];
    expected = lease->token;
    /* Claim the transition before touching slot metadata. A stale/double lease
     * cannot change a new owner's length, cancel a queued message or publish twice. */
    if (!atomic_compare_exchange_strong_explicit(
            &slot->control, &expected, (lease->token & ~3U) | QUEUED,
            memory_order_acq_rel, memory_order_relaxed)) return 0;
    if ((lease->capacity != slot->blocks * UART_TX_POOL_BLOCK_BYTES) ||
        (release == NULL && length > slot->blocks * UART_TX_POOL_BLOCK_BYTES)) {
        atomic_store_explicit(&slot->control, lease->token, memory_order_release);
        return 0;
    }
    slot->length = (uint32_t)length;
    slot->data = data;
    slot->release = release;
    slot->context = context;
    atomic_fetch_add_explicit(&s_pending_bytes, (unsigned int)length,
                              memory_order_relaxed);
    /* MPSC push-only publication. No producer dereferences head. The consumer
     * detaches a whole batch using exchange, not a CAS-pop which reads next.
     * Thus recycled head indices are safe here: a successful CAS always links
     * the current head, even if an index changed away and back (benign ABA). */
    head = atomic_load_explicit(&s_ready_head, memory_order_relaxed);
    do {
        slot->next = head;
    } while (!atomic_compare_exchange_weak_explicit(
        &s_ready_head, &head, lease->block + 1U,
        memory_order_acq_rel, memory_order_relaxed));
    ClearLease(lease); /* Do not access slot/data after publication. */
    return 1;
}

int UartTxPool_Commit(UartTxLease *lease, size_t length)
{
    return CommitPayload(lease, lease != NULL ? lease->data : NULL, length, NULL, 0U);
}
int UartTxPool_CommitReference(UartTxLease *descriptor, const uint8_t *data,
                              size_t length, UartTxReleaseFn release, uint32_t context)
{
    if (release == NULL) return 0;
    return CommitPayload(descriptor, data, length, release, context);
}

int UartTxPool_Cancel(UartTxLease *lease)
{
    Slot *slot;
    unsigned int expected;
    uint32_t mask;
    if (!LeaseValid(lease)) return 0;
    slot = &s_slots[lease->block];
    expected = lease->token;
    /* The owner alone reads blocks before ending ownership. */
    if (atomic_load_explicit(&slot->control, memory_order_acquire) != expected)
        return 0;
    mask = Mask(lease->block, slot->blocks);
    if (!atomic_compare_exchange_strong_explicit(
            &slot->control, &expected, lease->token & ~3U,
            memory_order_acq_rel, memory_order_relaxed)) return 0;
    atomic_fetch_and_explicit(&s_reserved, ~mask, memory_order_release);
    ClearLease(lease);
    return 1;
}

int UartTxPool_Begin(UartTxMessage *out)
{
    Slot *slot;
    uint32_t id;
    unsigned int control;
    if ((out == NULL) || (s_active != 0U)) return 0;
    if (s_batch == 0U) {
        uint32_t list = atomic_exchange_explicit(&s_ready_head, 0U,
                                                 memory_order_acquire);
        /* Reverse this detached immutable batch to restore commit order. New
         * publications stay on ready_head until this batch has been drained.
         * An acquired but uncommitted producer cannot block other commits. */
        while (list != 0U) {
            Slot *item = &s_slots[list - 1U];
            uint32_t next = item->next;
            item->next = s_batch;
            s_batch = list;
            list = next;
        }
    }
    if (s_batch == 0U) return 0;
    id = s_batch;
    slot = &s_slots[id - 1U];
    s_batch = slot->next;
    control = atomic_load_explicit(&slot->control, memory_order_relaxed);
    control = (control & ~3U) | IN_FLIGHT;
    atomic_store_explicit(&slot->control, control, memory_order_relaxed);
    out->data = slot->data;
    out->length = slot->length;
    out->block = id - 1U;
    out->token = control;
    s_active = id;
    return 1;
}

int UartTxPool_Finish(UartTxMessage *message)
{
    Slot *slot;
    uint32_t mask;
    uint32_t length;
    UartTxReleaseFn release;
    uint32_t context;
    unsigned int expected;
    if ((message == NULL) || (message->block >= UART_TX_POOL_BLOCKS) ||
        (s_active != message->block + 1U) ||
        ((message->token & 3U) != IN_FLIGHT)) return 0;
    slot = &s_slots[message->block];
    expected = message->token;
    if (atomic_load_explicit(&slot->control, memory_order_relaxed) != expected)
        return 0;
    mask = Mask(message->block, slot->blocks);
    length = slot->length;
    release = slot->release;
    context = slot->context;
    if (!atomic_compare_exchange_strong_explicit(
            &slot->control, &expected, message->token & ~3U,
            memory_order_release, memory_order_relaxed)) return 0;
    atomic_fetch_sub_explicit(&s_pending_bytes, length, memory_order_relaxed);
    atomic_fetch_and_explicit(&s_reserved, ~mask, memory_order_release);
    s_active = 0U;
    message->data = NULL;
    message->length = 0U;
    message->token = 0U;
    /* Slot may already be reused: only local callback/context are accessed. */
    if (release != NULL) release(context);
    return 1;
}

size_t UartTxPool_QueuedBytes(void)
{
    return atomic_load_explicit(&s_pending_bytes, memory_order_relaxed);
}

size_t UartTxPool_ReservedBlocks(void)
{
    uint32_t bitmap = atomic_load_explicit(&s_reserved, memory_order_relaxed);
    size_t count = 0U;
    while (bitmap != 0U) {
        bitmap &= bitmap - 1U;
        ++count;
    }
    return count;
}
