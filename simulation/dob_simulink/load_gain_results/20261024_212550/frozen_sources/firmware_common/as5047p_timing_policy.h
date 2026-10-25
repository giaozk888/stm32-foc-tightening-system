#ifndef AS5047P_TIMING_POLICY_H
#define AS5047P_TIMING_POLICY_H

/* Distinct contracts. Only the independent A timing candidate overrides the
 * transaction deadline; a late schedule must not inherit that relaxation. */
#ifndef AS_DMA_TRANSACTION_US
#define AS_DMA_TRANSACTION_US 200U
#endif
#define AS_DMA_TRANSACTION_WARN_US 200U
#define AS_DMA_SCHEDULE_LATE_US 200U
#define AS_DMA_GUARD_US 2U
#define AS_DMA_PERIOD_US 1000U
#define AS_DMA_SAMPLE_MAX_AGE_US 1500U
#define AS_DMA_CONTROL_WATCHDOG_US 2500U

#if AS_DMA_TRANSACTION_US < AS_DMA_TRANSACTION_WARN_US
#error Transaction warning cannot exceed the hard deadline
#endif
#if AS_DMA_TRANSACTION_US >= AS_DMA_PERIOD_US
#error Transaction must finish before the next acquisition period
#endif
#if AS_DMA_PERIOD_US + AS_DMA_TRANSACTION_US >= AS_DMA_SAMPLE_MAX_AGE_US
#error Preserve freshness headroom for one period plus transaction budget
#endif
#if AS_DMA_SAMPLE_MAX_AGE_US >= AS_DMA_CONTROL_WATCHDOG_US
#error Sample freshness must expire before the independent control watchdog
#endif
#endif
