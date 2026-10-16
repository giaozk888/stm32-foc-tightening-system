#define PW_LOG_MODULE_NAME "ALLOC"

#include "pw_allocator_port.h"

#include <cstddef>
#include <cstdint>

#include "main.h"
#include "FreeRTOS.h"
#include "task.h"
#include "pw_allocator/freertos_allocator.h"
#include "pw_allocator/layout.h"
#include "pw_log/log.h"

namespace {

struct AllocatorProbe {
  uint32_t marker;
  uint16_t samples[12];
};

PW_AllocatorDiagnostics_t diagnostics = {};

bool InInterruptContext() {
  return __get_IPSR() != 0U;
}

}  // namespace

extern "C" int PW_Allocator_RunSelfTest(void) {
  if (InInterruptContext() || xTaskGetSchedulerState() != taskSCHEDULER_RUNNING) {
    diagnostics.last_test_passed = 0U;
    return 0;
  }

  pw::allocator::FreeRtosAllocator& allocator =
      pw::allocator::GetFreeRtosAllocator();
  diagnostics.last_test_before_bytes =
      static_cast<uint32_t>(xPortGetFreeHeapSize());
  diagnostics.last_test_low_bytes = diagnostics.last_test_before_bytes;
  diagnostics.last_test_allocations = 0U;
  diagnostics.last_test_passed = 0U;

  void* raw = allocator.Allocate(pw::allocator::Layout(96U, 8U));
  if (raw == nullptr) {
    diagnostics.last_test_after_bytes =
        static_cast<uint32_t>(xPortGetFreeHeapSize());
    return 0;
  }
  diagnostics.last_test_allocations++;
  diagnostics.last_test_low_bytes =
      static_cast<uint32_t>(xPortGetFreeHeapSize());

  auto* probe = allocator.New<AllocatorProbe>();
  if (probe == nullptr) {
    allocator.Deallocate(raw);
    diagnostics.last_test_after_bytes =
        static_cast<uint32_t>(xPortGetFreeHeapSize());
    return 0;
  }
  diagnostics.last_test_allocations++;
  probe->marker = 0xA110CA7EU;
  probe->samples[0] = 0x474U;
  const bool contents_ok =
      probe->marker == 0xA110CA7EU && probe->samples[0] == 0x474U;

  const uint32_t current_free =
      static_cast<uint32_t>(xPortGetFreeHeapSize());
  if (current_free < diagnostics.last_test_low_bytes) {
    diagnostics.last_test_low_bytes = current_free;
  }

  allocator.Delete(probe);
  allocator.Deallocate(raw);
  diagnostics.last_test_after_bytes =
      static_cast<uint32_t>(xPortGetFreeHeapSize());
  diagnostics.last_test_passed =
      (contents_ok &&
       diagnostics.last_test_after_bytes == diagnostics.last_test_before_bytes)
          ? 1U
          : 0U;

  PW_LOG_INFO("pw_allocator test pass=%u allocs=%u before=%u low=%u after=%u",
              static_cast<unsigned>(diagnostics.last_test_passed),
              static_cast<unsigned>(diagnostics.last_test_allocations),
              static_cast<unsigned>(diagnostics.last_test_before_bytes),
              static_cast<unsigned>(diagnostics.last_test_low_bytes),
              static_cast<unsigned>(diagnostics.last_test_after_bytes));
  return diagnostics.last_test_passed != 0U ? 1 : 0;
}

extern "C" void PW_Allocator_GetDiagnostics(
    PW_AllocatorDiagnostics_t* output) {
  if (output == nullptr) {
    return;
  }
  *output = diagnostics;
  output->free_bytes = static_cast<uint32_t>(xPortGetFreeHeapSize());
  output->minimum_ever_free_bytes =
      static_cast<uint32_t>(xPortGetMinimumEverFreeHeapSize());
#if defined(PW_ALLOCATOR_HYBRID)
  output->hybrid_enabled = 1U;
  PW_Buffer_GetDiagnostics(&output->managed);
#endif
}
