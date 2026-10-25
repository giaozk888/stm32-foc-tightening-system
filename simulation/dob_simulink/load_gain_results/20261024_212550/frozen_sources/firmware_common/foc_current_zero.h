#ifndef FOC_CURRENT_ZERO_H
#define FOC_CURRENT_ZERO_H
#include <stdint.h>

/* Provisional bring-up quality gates, not a torque/current accuracy claim.
 * Feed UNFILTERED, simultaneous 20 kHz pairs with the power stage hard off.
 * One ISR owns Push; serialize foreground snapshots/restarts against that ISR.
 * No heap, floating point, RTOS calls or per-sample loops. */
enum {
    FOC_ZERO_SETTLE_PAIRS = 20000U,
    FOC_ZERO_WINDOW_PAIRS = 4000U,
    FOC_ZERO_MAX_SPAN = 100U,
    FOC_ZERO_MAX_HALF_DRIFT = 5U,
    FOC_ZERO_MAX_NOMINAL_DELTA = 100U,
    FOC_ZERO_MAX_RESTARTS = 8U,
    FOC_ZERO_TIMEOUT_MS = 5000U,
    FOC_ZERO_NOMINAL_MV = 1250U
};
typedef enum {
    FOC_ZERO_IDLE, FOC_ZERO_SETTLING, FOC_ZERO_COLLECTING,
    FOC_ZERO_READY, FOC_ZERO_FAILED
} FocZeroState;
typedef enum {
    FOC_ZERO_OK, FOC_ZERO_BAD_CONFIG, FOC_ZERO_OUT_OF_RANGE,
    FOC_ZERO_UNSTABLE, FOC_ZERO_TIMEOUT, FOC_ZERO_UNSAFE,
    FOC_ZERO_STOPPED, FOC_ZERO_RATE
} FocZeroReason;
typedef struct {
    FocZeroState state;
    FocZeroReason reason;
    uint32_t total, settled, count, restarts, span_restarts, drift_restarts;
    uint32_t sum_u, sum_v, first_u, first_v;
    uint16_t nominal, zero_u, zero_v;
    uint16_t min_u, max_u, min_v, max_v, last_u, last_v;
    uint16_t observed_min_u, observed_max_u, observed_min_v, observed_max_v;
} FocZeroCal;

void FocZero_Begin(FocZeroCal *cal, uint16_t nominal);
void FocZero_Push(FocZeroCal *cal, uint16_t u, uint16_t v);
void FocZero_Abort(FocZeroCal *cal, FocZeroReason reason);
void FocZero_Snapshot(const FocZeroCal *cal, FocZeroCal *snapshot);
#endif
