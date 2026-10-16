#ifndef FOC_CURRENT_PROTECTION_LAYERS_H
#define FOC_CURRENT_PROTECTION_LAYERS_H
#include "foc_overcurrent_confirm.h"

/* Integration is deliberately limited to host tests / power-hard-off fixtures.
 * This policy has NOT qualified a higher instantaneous limit for motor control.
 * An external hardware fault input mirrors an already asserted protection; it
 * does NOT implement, configure, or replace a comparator/TIM break connection.
 */
#if !(defined(FOC_PROTECTION_HOST_TEST) && FOC_PROTECTION_HOST_TEST == 1) && \
    !(defined(FOC_ISOLATED_CONCURRENCY) && FOC_ISOLATED_CONCURRENCY == 1 && \
      defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY) && FOC_ZERO_MEDIAN_COMPUTE_ONLY == 1) && \
    !(defined(FOC_OC_LAYERED_SELFTEST) && FOC_OC_LAYERED_SELFTEST == 1 && \
      defined(ZERO_RETEST_BOOT) && ZERO_RETEST_BOOT == 1)
#error Layered current protection is restricted to host or hard-off fixtures
#endif

typedef enum {
    FOC_PROTECT_NONE, FOC_PROTECT_MILD_CONFIRM,
    FOC_PROTECT_SEVERE_IMMEDIATE, FOC_PROTECT_SENSING_IMMEDIATE
} FocProtectionLayer;
typedef enum {
    FOC_PROTECT_STRICT_4A, FOC_PROTECT_OFFLINE_LAYERED
} FocProtectionMode;
enum {
    FOC_PROTECT_HW_OVERCURRENT = 1U,
    FOC_PROTECT_DRIVER_FAULT = 2U,
    FOC_PROTECT_ADC_INVALID = 4U,
    FOC_PROTECT_ADC_TIMEOUT = 8U,
    FOC_PROTECT_ZERO_INVALID = 16U,
    FOC_PROTECT_DMA_ERROR = 32U,
    FOC_PROTECT_KNOWN_FLAGS = 63U
};
typedef struct {
    FocOcConfirm core;
    uint32_t begin_us, fault_flags;
    FocProtectionLayer layer;
    FocProtectionMode mode;
    uint8_t initialized;
} FocCurrentProtection;

static inline FocOcConfirmResult FocProtection_Classify(FocCurrentProtection *s)
{
    switch (s->core.reason) {
    case FOC_OC_HARD:
        s->layer=FOC_PROTECT_SEVERE_IMMEDIATE; break;
    case FOC_OC_TWO_OF_THREE:
        s->layer=FOC_PROTECT_MILD_CONFIRM; break;
    case FOC_OC_NONE:
        s->layer=s->core.result==FOC_OC_PENDING ?
            FOC_PROTECT_MILD_CONFIRM : FOC_PROTECT_NONE; break;
    default:
        s->layer=FOC_PROTECT_SENSING_IMMEDIATE; break;
    }
    return s->core.result;
}
/* A malformed/missing severe boundary may not silently fall back to an
 * unlimited confirmation range. Strict mode demands exactly the existing 4 A.
 * Offline layered mode demands a finite boundary strictly above 4 A, solely
 * to test disjoint regions. Neither mode grants permission to energize power.
 */
static inline FocOcConfirmResult FocProtection_Begin(
    FocCurrentProtection *s, FocProtectionMode mode,
    FocOcConfirmConfig cfg, uint32_t now_us)
{
    *s=(FocCurrentProtection){0};
    s->mode=mode; s->begin_us=now_us; s->initialized=1U;
    FocOcConfirm_Begin(&s->core,cfg);
    if ((mode==FOC_PROTECT_STRICT_4A && cfg.hard_A!=FOC_OC_CONFIRM_SOFT_A) ||
        (mode==FOC_PROTECT_OFFLINE_LAYERED &&
         !(cfg.hard_A>FOC_OC_CONFIRM_SOFT_A)) ||
        (mode!=FOC_PROTECT_STRICT_4A && mode!=FOC_PROTECT_OFFLINE_LAYERED))
        FocOcConfirm_Trip(&s->core,FOC_OC_BAD_CONFIG,0U);
    return FocProtection_Classify(s);
}
/* Stop decisions are sticky. Keep accumulating external fault indications
 * without overwriting the first layer/cause. No auto-clear or output restart.
 */
static inline FocOcConfirmResult FocProtection_Health(
    FocCurrentProtection *s, uint32_t flags)
{
    s->fault_flags |= flags;
    if (s->core.result==FOC_OC_TRIPPED) return s->core.result;
    if (!s->initialized) {
        FocOcConfirm_Trip(&s->core,FOC_OC_BAD_CONFIG,0U);
        return FocProtection_Classify(s);
    }
    if (flags & (FOC_PROTECT_HW_OVERCURRENT|FOC_PROTECT_DRIVER_FAULT)) {
        /* Hardware protection must act outside this software path; this
         * records its indication without waiting for two ADC samples. */
        FocOcConfirm_Trip(&s->core,FOC_OC_HARD,0U);
        s->layer=FOC_PROTECT_SEVERE_IMMEDIATE;
    } else if (flags) {
        /* Unknown flags also fail closed, never silently ignored. */
        FocOcConfirm_Trip(&s->core,FOC_OC_BAD_SAMPLE,0U);
        s->layer=FOC_PROTECT_SENSING_IMMEDIATE;
    }
    return s->core.result;
}
/* Poll from a bounded time source, serialized with Push. The first-sample and
 * normal-stream deadlines matter even when no overcurrent is pending.
 * Called functions do not themselves produce a timer interrupt or shut PWM.
 */
static inline FocOcConfirmResult FocProtection_Poll(
    FocCurrentProtection *s, uint32_t now_us, uint32_t flags)
{
    if (FocProtection_Health(s,flags)==FOC_OC_TRIPPED) return s->core.result;
    if (FocOcConfirm_CheckDeadline(&s->core,now_us)==FOC_OC_TRIPPED)
        return FocProtection_Classify(s);
    uint32_t since=s->core.seq_valid ? s->core.last_us : s->begin_us;
    if ((uint32_t)(now_us-since)>FOC_OC_CONFIRM_MAX_US) {
        s->fault_flags |= FOC_PROTECT_ADC_TIMEOUT;
        FocOcConfirm_Trip(&s->core,FOC_OC_BAD_SAMPLE,0U);
        return FocProtection_Classify(s);
    }
    return s->core.result;
}
static inline FocOcConfirmResult FocProtection_Push(
    FocCurrentProtection *s, uint32_t seq, uint32_t now_us,
    uint16_t raw_u, uint16_t raw_v, uint8_t valid, uint32_t flags)
{
    if (!valid || raw_u>4095U || raw_v>4095U) flags |= FOC_PROTECT_ADC_INVALID;
    if (FocProtection_Poll(s,now_us,flags)==FOC_OC_TRIPPED) return s->core.result;
    /* Feed every physical callback, including filter warm-up/rejected pairs.
     * Filtered/replaced feedback is intentionally absent from this interface. */
    FocOcConfirm_Push(&s->core,seq,now_us,raw_u,raw_v,valid);
    return FocProtection_Classify(s);
}
#endif
