#include "pw_log_store.h"
#include <stdatomic.h>

_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "32-bit atomics required");
_Static_assert(sizeof(unsigned int) == sizeof(uint32_t), "32-bit unsigned required");
#define GENERATION_MASK 0xffff0000U
#define WRITING 0x8000U
#define REFERENCES 0x7fffU
typedef struct { atomic_uint control; PwLogRecord record; } Slot;
static Slot s_slots[PW_LOG_STORE_CAPACITY];

static Slot *Find(PwLogRef ref)
{
    uint32_t index = ref & 0xffffU;
    return (index > 0U && index <= PW_LOG_STORE_CAPACITY) ? &s_slots[index - 1U] : NULL;
}
static int Readable(unsigned int control, PwLogRef ref)
{
    return ((control & GENERATION_MASK) == (ref & GENERATION_MASK)) &&
           !(control & WRITING) && ((control & REFERENCES) != 0U);
}
void PwLogStore_Init(void)
{
    for (size_t i = 0; i < PW_LOG_STORE_CAPACITY; ++i)
        atomic_init(&s_slots[i].control, 0U);
}
int PwLogStore_Acquire(PwLogLease *out)
{
    if (out == NULL) return 0;
    for (uint32_t i = 0; i < PW_LOG_STORE_CAPACITY; ++i) {
        Slot *slot = &s_slots[i];
        unsigned int old = atomic_load_explicit(&slot->control, memory_order_relaxed);
        while ((old & (WRITING | REFERENCES)) == 0U) {
            unsigned int generation = (old + 0x10000U) & GENERATION_MASK;
            if (atomic_compare_exchange_weak_explicit(&slot->control, &old,
                    generation | WRITING | 1U, memory_order_acquire, memory_order_relaxed)) {
                out->ref = generation | (i + 1U);
                out->record = &slot->record;
                return 1;
            }
        }
    }
    return 0;
}
int PwLogStore_Seal(PwLogLease *lease, PwLogRef *out)
{
    Slot *slot = lease != NULL ? Find(lease->ref) : NULL;
    unsigned int expected;
    if (slot == NULL || out == NULL || lease->record != &slot->record) return 0;
    expected = (lease->ref & GENERATION_MASK) | WRITING | 1U;
    if (atomic_load_explicit(&slot->control, memory_order_relaxed) != expected) return 0;
    if (slot->record.length == 0U || slot->record.length >= PW_LOG_TEXT_BYTES ||
        slot->record.text[slot->record.length] != '\0') return 0;
    if (!atomic_compare_exchange_strong_explicit(&slot->control, &expected,
            expected & ~WRITING, memory_order_release, memory_order_relaxed)) return 0;
    *out = lease->ref;
    lease->ref = 0U; lease->record = NULL;
    return 1;
}
int PwLogStore_Cancel(PwLogLease *lease)
{
    Slot *slot = lease != NULL ? Find(lease->ref) : NULL;
    unsigned int expected;
    if (slot == NULL || lease->record != &slot->record) return 0;
    expected = (lease->ref & GENERATION_MASK) | WRITING | 1U;
    if (!atomic_compare_exchange_strong_explicit(&slot->control, &expected,
            expected & GENERATION_MASK, memory_order_release, memory_order_relaxed)) return 0;
    lease->ref = 0U; lease->record = NULL;
    return 1;
}
int PwLogStore_Retain(PwLogRef ref)
{
    Slot *slot = Find(ref);
    unsigned int old;
    if (slot == NULL) return 0;
    old = atomic_load_explicit(&slot->control, memory_order_relaxed);
    while (Readable(old, ref) && (old & REFERENCES) != REFERENCES) {
        if (atomic_compare_exchange_weak_explicit(&slot->control, &old, old + 1U,
                memory_order_acquire, memory_order_relaxed)) return 1;
    }
    return 0;
}
int PwLogStore_Release(PwLogRef ref)
{
    Slot *slot = Find(ref);
    unsigned int old;
    if (slot == NULL) return 0;
    old = atomic_load_explicit(&slot->control, memory_order_relaxed);
    while (Readable(old, ref)) {
        if (atomic_compare_exchange_weak_explicit(&slot->control, &old, old - 1U,
                memory_order_acq_rel, memory_order_relaxed)) return 1;
    }
    return 0;
}
const PwLogRecord *PwLogStore_View(PwLogRef owned_ref)
{
    Slot *slot = Find(owned_ref);
    if (slot == NULL || !Readable(atomic_load_explicit(&slot->control,
            memory_order_acquire), owned_ref)) return NULL;
    return &slot->record; /* caller must already own a reference throughout use */
}
size_t PwLogStore_Used(void)
{
    size_t used = 0U;
    for (size_t i = 0; i < PW_LOG_STORE_CAPACITY; ++i)
        if (atomic_load_explicit(&s_slots[i].control, memory_order_relaxed) &
            (WRITING | REFERENCES)) ++used;
    return used;
}
