/* Same fake port/state/fault assertions as generic engine, with the actual
 * compile-time binding mechanism used by the STM32 compact translation unit. */
#define AS_DMA_TEST_FIXED_OPS 1
#include "dma_engine_test.c"
#define AS_DMA_BIND_cs Cs
#define AS_DMA_BIND_guard Guard
#define AS_DMA_BIND_deadline Deadline
#define AS_DMA_BIND_start_word Start
#define AS_DMA_BIND_stop_word Stop
#define AS_DMA_BIND_busy Busy
#define AS_DMA_BIND_finish Finish
#define AS_DMA_BIND_fault_snapshot FaultSnapshot
#define AS_DMA_BIND(name, e) AS_DMA_BIND_##name
#define AS_DMA_HAS_FAULT_SNAPSHOT(e) 1
#include "../../firmware_common/as5047p_dma_engine.c"
