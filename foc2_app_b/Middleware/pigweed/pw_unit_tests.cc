#include <cstddef>
#include <cstdint>

#include "pw_log/log.h"
#include "pw_allocator_port.h"
#include "pw_unit_test/framework.h"
#include "pw_unit_test/logging_event_handler.h"
#include "ring_buffer.h"

namespace {

TEST(PwAllocator, FreeRtosHeapRoundTrip) {
  PW_AllocatorDiagnostics_t diagnostics = {};

  ASSERT_EQ(PW_Allocator_RunSelfTest(), 1);
  PW_Allocator_GetDiagnostics(&diagnostics);
  EXPECT_EQ(diagnostics.last_test_passed, 1U);
  EXPECT_EQ(diagnostics.last_test_allocations, 2U);
  EXPECT_EQ(diagnostics.last_test_before_bytes,
            diagnostics.last_test_after_bytes);
  EXPECT_GT(diagnostics.last_test_before_bytes, diagnostics.last_test_low_bytes);
}

TEST(RingBuffer, InitialStateAndCapacity) {
  uint8_t storage[8] = {};
  RingBuffer_t ring = {};

  RingBuffer_Init(&ring, storage, sizeof(storage));

  EXPECT_EQ(RingBuffer_Count(&ring), 0U);
  EXPECT_EQ(RingBuffer_Free(&ring), 7U);
}

TEST(RingBuffer, WriteReadWrapAround) {
  uint8_t storage[8] = {};
  RingBuffer_t ring = {};
  const uint8_t first[] = {1U, 2U, 3U, 4U, 5U, 6U};
  const uint8_t second[] = {7U, 8U, 9U, 10U, 11U};
  const uint8_t expected[] = {5U, 6U, 7U, 8U, 9U, 10U, 11U};
  uint8_t discarded[4] = {};
  uint8_t actual[7] = {};

  RingBuffer_Init(&ring, storage, sizeof(storage));
  ASSERT_EQ(RingBuffer_Write(&ring, first, sizeof(first)), sizeof(first));
  ASSERT_EQ(RingBuffer_Read(&ring, discarded, sizeof(discarded)),
            sizeof(discarded));
  ASSERT_EQ(RingBuffer_Write(&ring, second, sizeof(second)), sizeof(second));
  ASSERT_EQ(RingBuffer_Read(&ring, actual, sizeof(actual)), sizeof(actual));

  for (size_t i = 0; i < sizeof(expected); ++i) {
    EXPECT_EQ(actual[i], expected[i]);
  }
  EXPECT_EQ(RingBuffer_Count(&ring), 0U);
}

TEST(RingBuffer, FullBufferRejectsExtraByte) {
  uint8_t storage[8] = {};
  RingBuffer_t ring = {};
  const uint8_t input[] = {1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U};
  const uint8_t extra = 9U;

  RingBuffer_Init(&ring, storage, sizeof(storage));

  EXPECT_EQ(RingBuffer_Write(&ring, input, sizeof(input)), 7U);
  EXPECT_EQ(RingBuffer_Count(&ring), 7U);
  EXPECT_EQ(RingBuffer_Free(&ring), 0U);
  EXPECT_EQ(RingBuffer_Write(&ring, &extra, 1U), 0U);
}

TEST(RingBuffer, PeekAndConsumeClamp) {
  uint8_t storage[8] = {};
  RingBuffer_t ring = {};
  const uint8_t input[] = {21U, 22U, 23U};
  const uint8_t* view = nullptr;

  RingBuffer_Init(&ring, storage, sizeof(storage));
  ASSERT_EQ(RingBuffer_Write(&ring, input, sizeof(input)), sizeof(input));

  ASSERT_EQ(RingBuffer_PeekContiguous(&ring, &view), sizeof(input));
  ASSERT_NE(view, nullptr);
  EXPECT_EQ(view[0], 21U);
  EXPECT_EQ(view[2], 23U);

  RingBuffer_Consume(&ring, 99U);
  EXPECT_EQ(RingBuffer_Count(&ring), 0U);
  EXPECT_EQ(RingBuffer_PeekContiguous(&ring, &view), 0U);
  EXPECT_EQ(view, nullptr);
}

}  // namespace

extern "C" void PW_UnitTestsRun(void) {
  static pw::unit_test::LoggingEventHandler handler(false);

  PW_LOG_INFO("target unit tests begin (startup-only)");
  pw::unit_test::RegisterEventHandler(&handler);
  const int result = RUN_ALL_TESTS();
  pw::unit_test::RegisterEventHandler(nullptr);
  PW_LOG_INFO("target unit tests complete result=%d", result);
}
