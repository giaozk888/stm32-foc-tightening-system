#ifndef FOC_TIMEOUT_DIAG_H
#define FOC_TIMEOUT_DIAG_H
#include <stdint.h>
#include <stddef.h>

/* Diagnostic identifiers only. Existing fault values/thresholds stay intact. */
typedef enum {
    FOC_TO_NONE, FOC_TO_CURRENT_FIRST_SAMPLE, FOC_TO_CURRENT_SAMPLE,
    FOC_TO_CURRENT_CONFIRM, FOC_TO_ADC_GUARD, FOC_TO_ADC_CHAIN,
    FOC_TO_CONTROL_CHAIN, FOC_TO_OUTER_CONTROL, FOC_TO_ENCODER_TRANSACTION,
    FOC_TO_ENCODER_SAMPLE, FOC_TO_ENCODER_CONTROL, FOC_TO_ENCODER_SCHEDULE,
    FOC_TO_RUNDOWN, FOC_TO_STOP_SETTLE, FOC_TO_STALL_POSITION,
    FOC_TO_STALL_SPEED, FOC_TO_STARTUP_ZERO,
    FOC_TO_ENCODER_INTERVAL, FOC_TO_COMPUTE_DEADLINE,
    FOC_TO_BRIDGE_WINDOW, FOC_TO_BRIDGE_PAIR_BUDGET, FOC_TO_COMPUTE_WALL,
    FOC_TO_CONTROL_LEASE, FOC_TO_UNKNOWN
} FocTimeoutReason;

typedef struct {
    uint32_t reason, now_us, reference_us, elapsed_us, limit_us;
    uint32_t last_sample_us, pending_since_us, pending, misses;
} FocTimeoutEvidence;
/* Keep only non-derivable trigger values in the hot protection state. The
 * already-sticky pending/last fields are copied at shutdown, not duplicated. */
typedef struct {
    uint32_t reason, now_us, reference_us, limit_us;
} FocTimeoutLatch;

enum { FOC_DIAG_MOTOR=1U, FOC_DIAG_PROTECTION, FOC_DIAG_PROCESS,
       FOC_DIAG_STARTUP };

/* Native float copies in fault path; unit conversion/formatting is task-only.
 * Owner serializes capture/clear with PRIMASK; publish valid LAST with DMB.
 * Once published, immutable until reset/explicit existing clear-fault path. */
typedef struct {
    uint32_t valid, timestamp_ms, domain, fault_reason, timeout_reason;
    uint32_t motor_mode, tightening_state, state_elapsed_ms;
    float position_deg, position_target_deg, position_error_deg;
    float speed_raw_rpm, speed_filtered_rpm, speed_command_rpm;
    float iq_ref_A, iq_measured_A, id_measured_A, stall_elapsed_s;
    uint32_t contact_candidate_ms, encoder_valid, encoder_errors;
    uint32_t current_validator_state, current_suspect_total;
    uint32_t current_confirmed_spike, current_confirmed_transition;
    uint32_t current_unresolved_total, current_unresolved_consecutive;
    uint32_t current_unresolved_max_consecutive;
    uint32_t foc_cycles_max, foc_normal_cycles_max, foc_suspect_cycles_max;
    uint32_t foc_unresolved_cycles_max, foc_deadline_miss_count;
    uint32_t adc_sample_count, foc_exec_count, current_hold_total;
    uint32_t hold_window_count, hold_window_max, hold_rate_per_mille;
    uint32_t hold_window_ms, evidence_present, protection_flags;
    FocTimeoutEvidence timeout;
} FocFaultSnapshot;

#if defined(FOC_TIMEOUT_DIAGNOSTICS)
/* Pack only diagnostic IDs to keep the cold call within four ARM argument
 * registers. Original fault enums and the shutdown decision are unchanged. */
static void FaultDiag_CapturePacked(uint32_t domain_reason, FocTimeoutReason timeout,
                                   uint32_t elapsed_ms, uint32_t limit);
#define FaultDiag_Capture(domain,reason,timeout,elapsed,limit) \
    FaultDiag_CapturePacked((uint32_t)(domain)|((uint32_t)(reason)<<8),timeout,elapsed,limit)
#endif

typedef struct {
    uint32_t start_ms, previous_holds, previous_samples;
    uint32_t count, maximum, rate_per_mille, window_ms, max_window_ms;
    uint8_t initialized;
} FocHoldWindow;

/* Task-only 1 s nominal windows. Report actual duration, never claim that a
 * delayed task observed an exact 100 ms window. All ISR work is total++. */
static inline void FocHoldWindow_Update(FocHoldWindow *w, uint32_t now,
                                      uint32_t holds, uint32_t samples)
{
    if (!w->initialized) {
        w->initialized=1U; w->start_ms=now;
        w->previous_holds=holds; w->previous_samples=samples; return;
    }
    uint32_t elapsed=now-w->start_ms;
    if (elapsed<1000U) return;
    uint32_t dh=holds-w->previous_holds, ds=samples-w->previous_samples;
    w->count=dh; w->window_ms=elapsed;
    w->rate_per_mille=ds ? (uint32_t)((uint64_t)dh*1000U/ds) : 0U;
    if (dh>w->maximum) { w->maximum=dh; w->max_window_ms=elapsed; }
    w->start_ms=now; w->previous_holds=holds; w->previous_samples=samples;
}
#endif
