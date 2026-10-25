#ifndef FOC_ADC_RAW_BUFFER_H
#define FOC_ADC_RAW_BUFFER_H
/* C11 internal SPSC queue. The application uses foc_adc_timing_stm32.h.
 * One ADC ISR producer, one background consumer; Init only before either runs.
 * Two raw blocks, no allocation, waiting, sample-array copy or overwrite of a
 * READY/READING block. Atomic states are always lock-free 32-bit load/store.
 */
#include "foc_adc_window.h"
#include <stdatomic.h>
#include <stdint.h>

enum { FOC_RAW_FREE, FOC_RAW_FILLING, FOC_RAW_READY, FOC_RAW_READING };
typedef struct {
    uint16_t sample[FOC_SPREAD_BLOCK][2];
    uint16_t command_phase[3], command_trigger;
    uint32_t plan_sequence, sequence;
    uint8_t mixed;
} FocRawBlock;
typedef struct {
    FocRawBlock slot[2];
    atomic_uint state[2];
    /* Producer-only cursor. Atomic diagnostics are loaded by the consumer. */
    uint32_t count, write_slot, next_sequence;
    uint8_t discarding;
    atomic_uint dropped_blocks, dropped_samples, rejected_samples;
} FocRawBuffer;
typedef struct { const FocRawBlock *block; unsigned slot; } FocRawBlockView;
typedef struct {
    uint32_t dropped_blocks, dropped_samples, rejected_samples;
    unsigned ready, reading;
} FocRawBufferInfo;

void FocRawBuffer_Init(FocRawBuffer *q);
void FocRawBuffer_Push(FocRawBuffer *q, uint16_t u, uint16_t v,
                     uint16_t cu, uint16_t cv, uint16_t cw, uint16_t c4,
                     uint32_t plan_sequence);
/* A view stays immutable until Release. Only the single consumer may call
 * Acquire/Release; the producer may interrupt it between any instructions. */
int FocRawBuffer_Acquire(FocRawBuffer *q, FocRawBlockView *view);
void FocRawBuffer_Release(FocRawBuffer *q, const FocRawBlockView *view);
void FocRawBuffer_Info(const FocRawBuffer *q, FocRawBufferInfo *out);
#endif
