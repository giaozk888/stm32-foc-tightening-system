#ifndef FOC_HOT_PATH_H
#define FOC_HOT_PATH_H
#include <stdint.h>
#if defined(FOC_PREEMPT_COMMIT_PROBE) && defined(FOC_HEAVY_PROFILE_ENABLE) && !FOC_HEAVY_PROFILE_ENABLE
#define FOC_DETAIL_STATS 0
#else
#define FOC_DETAIL_STATS 1
#endif
#include "latest_original_profile.h"
/* Separate evidence candidate: keep the latest/original filter and all its
 * admission gates. Unlike FOC_IRQ_SOURCE_TRACE (inner FOC-work frame), the
 * timing adapter owns exactly one outer ADC IRQ frame in this mode. */
#if defined(FOC_PWM_BOUNDARY_TRACE) && \
    (!defined(FOC_ADC_RC_PROTECTED_CANDIDATE) || !defined(FOC_FEEDBACK_FAST_PATH) || \
     !defined(FOC_LATEST_ORIGINAL_FSM) || !defined(FOC_FAST_MATH) || \
     !defined(FOC_STARTUP_TRACE) || defined(FOC_IRQ_SOURCE_TRACE))
#error PWM boundary trace requires the RC original-FSM candidate and a single frame owner
#endif
#if defined(FOC_PWM_BOUNDARY_LITE) && \
    (!defined(FOC_ADC_RC_PROTECTED_CANDIDATE) || !defined(FOC_FEEDBACK_FAST_PATH) || \
     !defined(FOC_LATEST_ORIGINAL_FSM) || !defined(FOC_FAST_MATH) || \
     !defined(FOC_STARTUP_TRACE) || defined(FOC_IRQ_SOURCE_TRACE) || \
     defined(FOC_PWM_BOUNDARY_TRACE))
#error PWM boundary lite requires the RC original-FSM candidate without source tracing
#endif
#if defined(FOC_RC_DEFERRED_SHADOW) && \
    (!defined(FOC_PWM_BOUNDARY_LITE) || !defined(FOC_LATEST_ORIGINAL_FSM) || \
     !defined(FOC_ADC_RC_PROTECTED_CANDIDATE) || defined(FOC_ADAPTIVE_FILTER_EXPERIMENT))
#error Deferred plan shadow must be an output-locked RC boundary-lite observer
#endif
#if defined(FOC_COMPACT_CLOSED_LOOP) && \
    (!defined(FOC_PROTECTED_CLOSED_LOOP) || !defined(FOC_RAM_HOT_PATH) || \
     !defined(FOC_IRQ_COMPACT) || !defined(FOC_GATE_REUSE) || \
     defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_ZERO_TOTAL_BUDGET_OFF) || \
     defined(FOC_IRQ_SOURCE_TRACE))
#error Compact motor trial requires protected fixed-filter RAM/IRQ profile without experiment bypasses
#endif
#if defined(FOC_IRQ_COMPACT) && !defined(FOC_RAM_HOT_PATH)
#error Compact IRQ candidate requires an explicit RAM profile
#endif
#if defined(FOC_RAM_HOT_PATH) && (!defined(FOC_GATE_REUSE) || \
    (!defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) && !defined(FOC_COMPACT_CLOSED_LOOP) && !defined(FOC_LATEST_ORIGINAL_FSM)))
#error RAM timing requires the hard-off adaptive profile or separate protected compact trial
#endif
#if defined(FOC_FAST_REJECT_COMPUTE_ONLY)
#define FOC_PROFILE_HARD_OFF_TEXT "1"
#elif defined(FOC_COMPACT_CLOSED_LOOP) || defined(FOC_LATEST_ORIGINAL_FSM)
#define FOC_PROFILE_HARD_OFF_TEXT "0"
#else
#define FOC_PROFILE_HARD_OFF_TEXT "1"
#endif
/* Existing CRT copies .RamFunc with .data before enabling interrupts. DMA
 * payloads remain in their original storage; no CCM alias or heap relocation.
 * Host replays exercise the same arithmetic without an MCU memory section. */
#if defined(FOC_RAM_HOT_PATH) && defined(__arm__)
#define FOC_RAM_PATH __attribute__((section(".RamFunc.foc")))
#else
#define FOC_RAM_PATH
#endif
/* Inline small register predicates in each ISR, not the whole guardian/fault
 * graph. Keep this opt-in: previous measured images retain their own layout. */
#if defined(FOC_IRQ_COMPACT)
#define FOC_COMPACT_HELPER static inline __attribute__((always_inline))
#else
#define FOC_COMPACT_HELPER FOC_HOT_PATH static
#endif
#if (defined(FOC_GATE_REUSE) || defined(FOC_IRQ_SOURCE_TRACE)) && !defined(FOC_FEEDBACK_FAST_PATH)
#error Gate reuse and IRQ source tracing require the independent feedback-fast candidate
#endif
#if defined(FOC_FEEDBACK_FAST_PATH) && !defined(FOC_GUARD_FAST_PATH)
#error Feedback fast path requires the separate integer-guard candidate
#endif
#if defined(FOC_GUARD_FAST_PATH) && !defined(FOC_PAIR_FAST_PATH)
#error Guard fast path requires the separate protected pair-fast candidate
#endif
/* Separate candidate only; no global fast-math or protection policy changes. */
#if defined(FOC_PAIR_FAST_PATH)
#if !defined(FOC_FAST_MATH) || !defined(FOC_PROTECTED_CLOSED_LOOP) || \
    !defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
#error Pair optimization requires protected fast-math and encoder preemption
#endif
#if !defined(__GNUC__) || defined(__clang__) || defined(__FAST_MATH__)
#error Pair optimization requires GCC without fast-math
#endif
#define FOC_HOT_PATH FOC_RAM_PATH __attribute__((optimize("O2")))
#else
#define FOC_HOT_PATH
#endif
#if defined(FOC_FEEDBACK_FAST_PATH)
/* Keep the pure feedback kernels in their O2 hot caller, not outlined Os
 * helpers. No arithmetic policy, finite checks or public API is changed. */
#define FOC_HOT_INLINE static inline __attribute__((always_inline))
#else
#define FOC_HOT_INLINE static inline
#endif
/* One physical frame's measured intervals, NOT sums of separate maxima.
 * wall_cyc/irq_cyc have the same DWT boundaries; pair/math include preemption.
 * A first-late snapshot is copied only AFTER emergency output closure. */
typedef struct {
    uint32_t seq, elapsed_us, pair_us, math_us, wall_cyc, irq_cyc;
    uint8_t valid;
} FocFrameCost;
#endif
