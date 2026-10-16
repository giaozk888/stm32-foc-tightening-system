#include "pw_managed_buffer.h"

#include <atomic>
#include "pw_allocator/freertos_allocator.h"
#include "pw_allocator/layout.h"

#if defined(PW_BUFFER_HOST_TEST)
#include <mutex>
#include "pw_buffer_test_heap.h"
#else
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#endif

namespace {
enum State : uint8_t { free_slot, writing, sealed };
struct Slot {
    uint8_t *data = nullptr;
    size_t bytes = 0;
    uint32_t generation = 0;
    uint16_t owners = 0;
    State state = free_slot;
    PW_BufferTag tag = PW_BUFFER_TEMP;
};
Slot slots[PW_BUFFER_SLOTS];
PW_BufferDiagnostics stats{};
std::atomic<uint32_t> rejected{0};
constexpr uint32_t max_generation = UINT32_MAX >> 5U;
#if !defined(PW_BUFFER_HOST_TEST)
bool InInterrupt() {
    uint32_t ipsr;
    __asm volatile("mrs %0, ipsr" : "=r"(ipsr));
    return ipsr != 0U;
}
bool InterruptsEnabled() {
    uint32_t basepri, primask;
    __asm volatile("mrs %0, basepri" : "=r"(basepri));
    __asm volatile("mrs %0, primask" : "=r"(primask));
    return basepri == 0U && primask == 0U;
}
#endif

bool Allowed() {
#if defined(PW_BUFFER_HOST_TEST)
    const bool ok = PW_BufferTest_Allowed() != 0;
#else
    const bool ok = !InInterrupt() && InterruptsEnabled() &&
                    xTaskGetSchedulerState() == taskSCHEDULER_RUNNING &&
                    uxTaskPriorityGet(nullptr) <= 2U;
#endif
    if (!ok)
        rejected.fetch_add(1, std::memory_order_relaxed);
    return ok;
}
#if defined(PW_BUFFER_HOST_TEST)
std::mutex mutex;
using Guard = std::lock_guard<std::mutex>;
std::mutex &Mutex() {
    return mutex;
}
void Suspend() {
    PW_BufferTest_Suspend();
}
void Resume() {
    PW_BufferTest_Resume();
}
size_t FreeHeap() {
    return PW_BufferTest_FreeHeap();
}
#else
StaticSemaphore_t mutex_storage;
SemaphoreHandle_t mutex = nullptr;
SemaphoreHandle_t Mutex() {
    taskENTER_CRITICAL();
    if (mutex == nullptr)
        mutex = xSemaphoreCreateMutexStatic(&mutex_storage);
    taskEXIT_CRITICAL();
    return mutex;
}
class Guard {
  public:
    explicit Guard(SemaphoreHandle_t value) : value_(value) {
        (void)xSemaphoreTake(value_, portMAX_DELAY);
    }
    ~Guard() {
        (void)xSemaphoreGive(value_);
    }

  private:
    SemaphoreHandle_t value_;
};
void Suspend() {
    vTaskSuspendAll();
}
void Resume() {
    (void)xTaskResumeAll();
}
size_t FreeHeap() {
    return xPortGetFreeHeapSize();
}
#endif

Slot *Find(uint32_t token, State expected) {
    const uint32_t id = token & 31U;
    if (id == 0 || id > PW_BUFFER_SLOTS)
        return nullptr;
    Slot &slot = slots[id - 1];
    return slot.state == expected && slot.generation == (token >> 5U) ? &slot : nullptr;
}
Slot *Writer(const PW_BufferLease *lease) {
    if (lease == nullptr)
        return nullptr;
    Slot *slot = Find(lease->token, writing);
    return slot && slot->data == lease->data && slot->bytes == lease->capacity ? slot : nullptr;
}
void Free(Slot &slot) {
    pw::allocator::GetFreeRtosAllocator().Deallocate(slot.data);
    stats.live_bytes -= static_cast<uint32_t>(slot.bytes);
    stats.tag_bytes[slot.tag] -= static_cast<uint32_t>(slot.bytes);
    --stats.live_objects;
    ++stats.frees;
    slot.data = nullptr;
    slot.bytes = 0;
    slot.owners = 0;
    slot.state = free_slot;
}
} // namespace

extern "C" int PW_Buffer_ContextAllowed(void) {
    return Allowed() ? 1 : 0;
}

extern "C" int PW_Buffer_Allocate(size_t bytes, PW_BufferTag tag, PW_BufferLease *out) {
    if (!Allowed())
        return 0;
    Guard lock(Mutex());
    if (out == nullptr || bytes == 0 || bytes > PW_BUFFER_MAX_BYTES ||
        static_cast<unsigned>(tag) >= PW_BUFFER_TAG_COUNT ||
        bytes > PW_BUFFER_TOTAL_BYTES - stats.live_bytes) {
        ++stats.allocation_failures;
        return 0;
    }
    for (size_t i = 0; i < PW_BUFFER_SLOTS; ++i) {
        Slot &slot = slots[i];
        // Never wrap a token and accidentally revive a stale owner.
        if (slot.state != free_slot || slot.generation == max_generation)
            continue;
        uint8_t *data = nullptr;
        // Prevent other task-level heap users from racing the reserve check.
        // heap_4 supports nested scheduler suspension; no mutex is acquired here.
        Suspend();
        if (FreeHeap() >= PW_BUFFER_HEAP_RESERVE + bytes) {
            data = static_cast<uint8_t *>(
                pw::allocator::GetFreeRtosAllocator().Allocate(pw::allocator::Layout(bytes, 8)));
            if (data != nullptr && FreeHeap() < PW_BUFFER_HEAP_RESERVE) {
                pw::allocator::GetFreeRtosAllocator().Deallocate(data);
                data = nullptr;
            }
        }
        Resume();
        if (data == nullptr) {
            ++stats.allocation_failures;
            return 0;
        }
        slot.data = data;
        slot.bytes = bytes;
        slot.tag = tag;
        slot.state = writing;
        slot.owners = 1;
        ++slot.generation;
        stats.live_bytes += static_cast<uint32_t>(bytes);
        stats.tag_bytes[tag] += static_cast<uint32_t>(bytes);
        ++stats.live_objects;
        ++stats.allocations;
        if (stats.live_bytes > stats.peak_bytes)
            stats.peak_bytes = stats.live_bytes;
        *out = {data, bytes, (slot.generation << 5U) | static_cast<uint32_t>(i + 1)};
        return 1;
    }
    ++stats.allocation_failures;
    return 0;
}

extern "C" int PW_Buffer_Cancel(PW_BufferLease *lease) {
    if (!Allowed())
        return 0;
    Guard lock(Mutex());
    Slot *slot = Writer(lease);
    if (slot == nullptr) {
        ++stats.invalid_owners;
        return 0;
    }
    Free(*slot);
    *lease = {};
    return 1;
}
extern "C" int PW_Buffer_Seal(PW_BufferLease *lease, PW_BufferRef *out) {
    if (!Allowed())
        return 0;
    Guard lock(Mutex());
    Slot *slot = Writer(lease);
    if (slot == nullptr || out == nullptr) {
        ++stats.invalid_owners;
        return 0;
    }
    slot->state = sealed;
    *out = lease->token;
    *lease = {};
    return 1;
}
extern "C" int PW_Buffer_Retain(PW_BufferRef ref) {
    if (!Allowed())
        return 0;
    Guard lock(Mutex());
    Slot *slot = Find(ref, sealed);
    if (slot == nullptr || slot->owners == UINT16_MAX) {
        ++stats.invalid_owners;
        return 0;
    }
    ++slot->owners;
    return 1;
}
extern "C" int PW_Buffer_Release(PW_BufferRef ref) {
    if (!Allowed())
        return 0;
    Guard lock(Mutex());
    Slot *slot = Find(ref, sealed);
    if (slot == nullptr) {
        ++stats.invalid_owners;
        return 0;
    }
    if (--slot->owners == 0)
        Free(*slot);
    return 1;
}
extern "C" const uint8_t *PW_Buffer_View(PW_BufferRef ref, size_t *capacity) {
    if (!Allowed())
        return nullptr;
    Guard lock(Mutex());
    Slot *slot = Find(ref, sealed);
    if (slot == nullptr) {
        ++stats.invalid_owners;
        return nullptr;
    }
    if (capacity != nullptr)
        *capacity = slot->bytes;
    return slot->data;
}
extern "C" void PW_Buffer_GetDiagnostics(PW_BufferDiagnostics *out) {
    if (out == nullptr)
        return;
#if !defined(PW_BUFFER_HOST_TEST)
    if (InInterrupt() || !InterruptsEnabled() || xTaskGetSchedulerState() != taskSCHEDULER_RUNNING)
        return;
#endif
    Guard lock(Mutex());
    *out = stats;
    out->context_rejections = rejected.load(std::memory_order_relaxed);
}
