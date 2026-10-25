#ifndef AS5047P_DMA_ENGINE_H
#define AS5047P_DMA_ENGINE_H

#include <stdint.h>
#include "as5047p_timing_policy.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    AS_DMA_OK = 0, AS_DMA_PENDING, AS_DMA_TIMEOUT, AS_DMA_PARITY,
    AS_DMA_EF, AS_DMA_IO, AS_DMA_CANCELLED, AS_DMA_SCHEDULE, AS_DMA_CONTROL_STALE
} AsDmaStatus;
typedef enum {
    AS_DMA_IDLE = 0, AS_DMA_SETUP, AS_DMA_WORD, AS_DMA_TAIL,
    AS_DMA_HOLD, AS_DMA_GAP
} AsDmaState;

typedef struct {
    AsDmaStatus status;
    /* sample_us retains the port's RX-IRQ receipt-time convention, not a
     * hardware-latched magnetic sample aperture. elapsed_us is protocol
     * completion duration; freshness and control-consumption age are separate. */
    uint32_t sequence, sample_us, completed_us, elapsed_us;
    uint16_t raw, response, errfl;
    uint8_t errfl_valid, recovered;
} AsDmaSample;

#if defined(AS5047P_DMA_TIMING_POLICY_V2)
typedef struct { uint32_t slow_count,ok_max_us; } AsDmaTimingStats;
static inline void AsDmaTiming_Record(AsDmaTimingStats *stats,const AsDmaSample *sample)
{
    if (sample->status!=AS_DMA_OK) return;
    if (sample->elapsed_us>=AS_DMA_TRANSACTION_WARN_US) ++stats->slow_count;
    if (sample->elapsed_us>stats->ok_max_us) stats->ok_max_us=sample->elapsed_us;
}
#endif

typedef struct { uint32_t sequence, sample_us; uint8_t valid; } AsDmaCursor;
/* Snapshot consumer: 1 = new valid sample, 0 = pending/duplicate,
 * -1 = failed/stale/invalid interval. dt is actual timer time, not task ticks. */
int AsDma_Consume(AsDmaCursor *cursor, const AsDmaSample *sample,
                  uint32_t now_us, uint32_t *dt_us);

/* All hooks are bounded. No sleeping, logging, RTOS API, HAL wait loops or
 * heap allocation. Caller serializes task access with the ISR state owner. */
typedef struct AsDmaEngine AsDmaEngine;
typedef struct {
    void (*cs)(void *context, int high);
    void (*guard)(void *context, uint32_t due_us);
    void (*deadline)(void *context, int enable, uint32_t due_us);
    int (*start_word)(void *context, volatile uint16_t *tx, volatile uint16_t *rx);
    void (*stop_word)(void *context);
    int (*busy)(void *context);
    void (*finish)(void *context, AsDmaStatus status);
    /* Called on a failed transaction BEFORE stop_word clears DMA/SPI state. */
    void (*fault_snapshot)(void *context, const AsDmaEngine *engine,
                           AsDmaStatus status, uint32_t now_us);
} AsDmaOps;

struct AsDmaEngine {
    const AsDmaOps *ops;
    void *context;
    AsDmaState state;
    uint32_t started_us, deadline_us, guard_us, word_rx_us;
    uint32_t attempts, successes, failures, max_elapsed_us;
    uint16_t reg, response, errfl;
    volatile uint16_t tx, rx; /* static driver instance: never task-stack DMA */
    uint8_t frame, errfl_valid, recovered;
    AsDmaSample sample;
};

/* Time intervals must be <2^31 us; wrap at ~71 min is intentional. */
int AsDma_TimeReached(uint32_t now, uint32_t due);
void AsDma_Init(AsDmaEngine *engine, const AsDmaOps *ops, void *context);
int AsDma_Begin(AsDmaEngine *engine, uint16_t reg, uint32_t now_us);
void AsDma_Guard(AsDmaEngine *engine, uint32_t now_us);
void AsDma_RxComplete(AsDmaEngine *engine, uint32_t now_us);
void AsDma_CheckDeadline(AsDmaEngine *engine, uint32_t now_us);
void AsDma_Fail(AsDmaEngine *engine, AsDmaStatus status, uint32_t now_us);

#ifdef __cplusplus
}
#endif
#endif
