#ifndef FOC_ZERO_ROBUST_H
#define FOC_ZERO_ROBUST_H
#include "foc_current_zero.h"
/* Independent zero estimator. Five-sample block
 * medians, eight 500-physical-pair segments; no samples/time are compressed.
 * All segment means must agree within the EXISTING five-count drift limit.
 * No per-segment outlier quota; segment counters are diagnostic only.
 * FOC_ZERO_TOTAL_BUDGET_OFF is the historical hard-off experiment.
 * FOC_LATEST_ZERO_COUNT_ONLY explicitly selects count-only totals in the
 * latest/original-FSM candidate. Neither changes burst, ADC validity, center
 * span, within-block span, nominal offset, or segment drift checks. */
#if defined(FOC_ZERO_ALL_REJECTED_DIAG) && \
    (!defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || !defined(FOC_ZERO_TOTAL_BUDGET_OFF) || \
     !defined(FOC_PROTECTED_CLOSED_LOOP) || defined(FOC_LATEST_ORIGINAL_FSM) || \
     defined(FOC_COMPACT_CLOSED_LOOP))
#error All-rejected zero policy is restricted to the power-hard-off diagnostic
#endif
/* Diagnostic comparison ONLY: a pair is rejected if EITHER channel differs
 * from its own five-point median by >40 counts. The burst condition then
 * trips only when ALL five PAIRS are rejected. Other validity/quality gates
 * remain independent. One surviving pair is NOT a control-quality proof. */
#if defined(FOC_LATEST_ZERO_COUNT_ONLY) && !defined(FOC_LATEST_ORIGINAL_FSM)
#error Count-only latest zero policy requires the latest/original-FSM profile
#endif
enum { FOC_ROBUST_BLOCK=5U, FOC_ROBUST_SEGMENT=500U,
       FOC_ROBUST_OUTLIER_DELTA=40U, FOC_ROBUST_INLIER_SPAN=FOC_ZERO_MAX_SPAN,
       FOC_ROBUST_MAX_OUTLIERS=20U };
enum { FOC_ROBUST_BAD_ADC=1U, FOC_ROBUST_BAD_NOMINAL=2U,
       FOC_ROBUST_BURST=4U, FOC_ROBUST_TOTAL_BUDGET=8U,
       /* Bit 16 is reserved for historical segment-budget receipts. */
       FOC_ROBUST_BAD_INLIERS=32U,
       FOC_ROBUST_CENTER_SPAN=64U, FOC_ROBUST_SEGMENT_DRIFT=128U };
typedef struct {
    uint16_t u[5],v[5];
    uint16_t flags;
    uint8_t fill,segments;
    uint32_t outliers,segment_outliers,segment_u,segment_v;
    uint32_t segment_min_u,segment_max_u,segment_min_v,segment_max_v;
} FocZeroRobust;
void FocZeroRobust_Begin(FocZeroRobust *s);
void FocZeroRobust_Push(FocZeroRobust *s,FocZeroCal *c,uint16_t u,uint16_t v);
#endif
