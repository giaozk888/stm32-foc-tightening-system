#ifndef AS5047P_DMA_STM32_H
#define AS5047P_DMA_STM32_H
#include "as5047p_dma_engine.h"
#ifdef __cplusplus
extern "C" {
#endif

typedef void (*AsDmaFaultHook)(void); /* ISR-safe: no RTOS, logging or blocking */
typedef struct {
    uint32_t attempts, successes, failures, max_elapsed_us;
    uint32_t timeouts, dma_errors, schedule_misses, control_stale;
    uint32_t last_elapsed_us, last_status, periodic;
} AsDmaStats;

/* First non-cancellation fault. Legacy captures before DMA/SPI reset. In the
 * FOC-first error top half, DMA ISR / SPI SR flags are preserved before ACK;
 * other registers are captured by deferred service (e.g. CCR may be disabled).
 * Read-only evidence; reading/publishing it never changes protection. */
typedef struct {
    uint32_t valid, status, phase, frame;
    uint32_t started_us, now_us, deadline_us, guard_us;
    uint32_t spi_sr, spi_cr1, spi_cr2, dma_isr;
    uint32_t rx_ndtr, tx_ndtr, rx_ccr, tx_ccr;
    uint32_t tim_sr, tim_dier, ipsr;
    /* TIM2 IRQ entry BEFORE clearing CC flags; available in priority-fix build. */
    uint32_t tim_entry_valid, tim_entry_us, tim_entry_sr, tim_entry_dier;
    uint32_t tim_entry_ccr2, tim_entry_late_us, guard_max_late_us;
} AsDmaFaultSnapshot;

int AS5047P_DmaInit(AsDmaFaultHook hook);
uint32_t AS5047P_DmaNowUs(void);
int AS5047P_DmaStartPeriodic(void);
void AS5047P_DmaStopPeriodic(void);
int AS5047P_DmaIsPeriodic(void);
int AS5047P_DmaGetSample(AsDmaSample *sample);
/* Non-mutating telemetry snapshot: no deadline check, SPI start or control ACK.
 * Legacy uses a short masked section. FOC-first reads the last complete bank
 * without masking; the subsequent timer read is a conservative age bound. */
int AS5047P_DmaSnapshot(AsDmaSample *sample, uint32_t *now_us);
void AS5047P_DmaAcknowledgeControl(void);
void AS5047P_DmaGetStats(AsDmaStats *stats);
#if defined(AS5047P_DMA_TIMING_POLICY_V2)
void AS5047P_DmaGetTimingStats(uint32_t *slow_count,uint32_t *ok_max_us);
#endif
void AS5047P_DmaGetFaultSnapshot(AsDmaFaultSnapshot *snapshot);
/* Diagnostic status published BEFORE invoking the existing output-off hook. */
uint32_t AS5047P_DmaFaultStatus(void);
/* Startup / SAFE diagnostics only: CPU-bounded polling adapter, not the
 * periodic control path. Returns AS_DMA_* and never falls back to HAL SPI. */
AsDmaStatus AS5047P_DmaReadOne(uint16_t reg, uint16_t *response);
#ifdef __cplusplus
}
#endif
#endif
