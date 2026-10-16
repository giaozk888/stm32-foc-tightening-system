#include "FreeRTOS.h"
#include "pw_buffer_test_heap.h"
#include <cassert>
#include <cstdlib>
#include <mutex>
#include <unordered_map>

namespace {
std::recursive_mutex heap_mutex;
std::unordered_map<void *, size_t> allocations;
size_t limit = 40U * 1024U, used = 0;
bool fail = false;
thread_local int in_isr = 0, scheduler = 1;
thread_local unsigned task_priority = 1;
thread_local int masked = 0;
} // namespace
extern "C" int PW_BufferTest_Allowed() {
    return !in_isr && !masked && scheduler && task_priority <= 2;
}
extern "C" void PW_BufferTest_SetMasked(int value) {
    masked = value;
}
extern "C" void PW_BufferTest_SetContext(int isr, int running, unsigned priority) {
    in_isr = isr;
    scheduler = running;
    task_priority = priority;
}
extern "C" void PW_BufferTest_Suspend() {
    heap_mutex.lock();
}
extern "C" void PW_BufferTest_Resume() {
    heap_mutex.unlock();
}
extern "C" size_t PW_BufferTest_FreeHeap() {
    std::lock_guard lock(heap_mutex);
    return limit - used;
}
extern "C" void PW_BufferTest_SetFreeHeap(size_t bytes) {
    std::lock_guard lock(heap_mutex);
    limit = used + bytes;
}
extern "C" void PW_BufferTest_FailAllocation(int value) {
    std::lock_guard lock(heap_mutex);
    fail = value != 0;
}
extern "C" size_t PW_BufferTest_LiveAllocations() {
    std::lock_guard lock(heap_mutex);
    return allocations.size();
}
extern "C" void *pvPortMalloc(size_t bytes) {
    std::lock_guard lock(heap_mutex);
    // Model heap_4 alignment and header charge, not a substitute allocator API.
    const size_t charged = ((bytes + 7U) & ~size_t(7U)) + 8U;
    if (fail || charged > limit - used)
        return nullptr;
    void *pointer = std::malloc(bytes);
    if (pointer != nullptr) {
        allocations[pointer] = charged;
        used += charged;
    }
    return pointer;
}
extern "C" void vPortFree(void *pointer) {
    std::lock_guard lock(heap_mutex);
    const auto found = allocations.find(pointer);
    assert(found != allocations.end());
    used -= found->second;
    allocations.erase(found);
    std::free(pointer);
}
