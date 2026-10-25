#ifndef FOC_FEEDBACK_BINDING_STM32_H
#define FOC_FEEDBACK_BINDING_STM32_H
#if !defined(FOC_FEEDBACK_SAFETY_BINDING) || FOC_FEEDBACK_SAFETY_BINDING != 1 || \
    !defined(FOC_ISOLATED_CONCURRENCY) || FOC_ISOLATED_CONCURRENCY != 1 || \
    !defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY) || FOC_ZERO_MEDIAN_COMPUTE_ONLY != 1 || \
    !defined(FOC_ADC_WINDOW) || FOC_ADC_WINDOW != 1 || \
    !defined(AS5047P_SPI_DMA) || AS5047P_SPI_DMA != 1 || \
    defined(FOC_RAW_OBSERVE_ONLY) || defined(FOC_FILTERED_OBSERVE_ONLY) || \
    defined(ZERO_RETEST_BOOT) || defined(SWITCH_FEEDBACK_DIAGNOSTIC) || \
    defined(FOC_ZERO_FAILURE_TRACE) || defined(TIGHTEN_SYNTHETIC_BENCH) || \
    defined(FOC_OC_LAYERED_SELFTEST)
#error Feedback binding requires standalone hard-off compute, without observation bypasses
#endif
#include "foc_feedback_safety_candidate.h"
enum { FOC_FB_ENCODER_INVALID = 32U, FOC_FB_CORE_FAULT = 64U,
       FOC_FB_TIMER_INVALID = 128U, FOC_FB_COMPUTE_LATE = 256U };
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
enum { FOC_FB_CONTROL_LEASE_EXPIRED = 512U };
#endif
/* User-selected doubled repair allowance, HARD-OFF diagnosis only.
 * Keep window length, filter classifier, current confirmation and deadlines.
 * These values have not qualified powered motor feedback. */
enum { FOC_FB_REPAIR_HITS_PER_32 = 6U, FOC_FB_REPAIR_STREAK = 4U };
/* Fault/ISR entry only. NOT a motor-control/enable interface. */
void FocFeedbackBinding_EmergencyOff(uint32_t flags);
#endif
