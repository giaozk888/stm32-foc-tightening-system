#ifndef FOC_ZERO_MEDIAN_H
#define FOC_ZERO_MEDIAN_H
#include "foc_current_zero.h"
#include "foc_current_median.h"
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
#include "foc_zero_robust.h"
#endif
/* Diagnostic contrast only. A filtered READY does not override raw failure. */
typedef struct {
    FocZeroCal raw;
    uint16_t u[FOC_CURRENT_HISTORY_PAIRS], v[FOC_CURRENT_HISTORY_PAIRS], min_u, max_u, min_v, max_v;
    uint32_t pairs, changed, outside_nominal, raw_window_pairs;
    uint8_t index;
#if (defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM))
    FocZeroRobust robust;
#endif
} FocZeroMedian;
void FocZeroMedian_Begin(FocZeroMedian *m, FocZeroCal *filtered, uint16_t nominal);
void FocZeroMedian_Push(FocZeroMedian *m, FocZeroCal *filtered, uint16_t u, uint16_t v);
#endif
