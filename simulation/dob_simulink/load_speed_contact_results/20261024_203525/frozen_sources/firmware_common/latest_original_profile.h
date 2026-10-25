#ifndef LATEST_ORIGINAL_PROFILE_H
#define LATEST_ORIGINAL_PROFILE_H
#if defined(FOC_STARTUP_TRACE) && !defined(FOC_LATEST_ORIGINAL_FSM)
#error Startup evidence requires the latest/original protected integration
#endif
#if defined(FOC_LATEST_ZERO_COUNT_ONLY) && !defined(FOC_LATEST_ORIGINAL_FSM)
#error Count-only latest zero policy requires the latest/original-FSM profile
#endif
/* A distinct integration candidate, not a power-unlock of the hard-off
 * adaptive experiment. The original application FSM remains the command owner. */
#if defined(FOC_LATEST_ORIGINAL_FSM)
#if !defined(FOC_PROTECTED_CLOSED_LOOP) || !defined(FOC_RAM_HOT_PATH) || \
    !defined(FOC_IRQ_COMPACT) || !defined(FOC_GATE_REUSE) || \
    defined(FOC_COMPACT_CLOSED_LOOP) || defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || \
    defined(FOC_ZERO_TOTAL_BUDGET_OFF) || defined(FOC_IRQ_SOURCE_TRACE) || \
    defined(FOC_ORIGINAL_CLOSED_LOOP_UPDATED)
#error Latest/original integration requires its complete protected profile without diagnostic bypasses
#endif
#endif
/* Reset only current PI memory, never application position/speed/FSM state. */
static inline void FocCurrentPi_Reset(volatile float *d, volatile float *q)
{
    *d = 0.0f;
    *q = 0.0f;
}
#endif
