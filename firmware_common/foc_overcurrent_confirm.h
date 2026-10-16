#ifndef FOC_OVERCURRENT_CONFIRM_H
#define FOC_OVERCURRENT_CONFIRM_H
#include <float.h>
#include <stdint.h>
#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__)
#error Overcurrent candidate requires finite-value checks; do not use fast-math
#endif

/* OFFLINE CANDIDATE ONLY: not wired to either application's power gate.
 * Inputs are consecutive PHYSICAL U/V pairs, never repaired feedback.
 * A higher hard_A is a test parameter, NOT a qualified hardware setting.
 * One serialized owner must perform Begin/Push/CheckDeadline. A timer and
 * ADC ISR may NOT concurrently update this state without bounded exclusion.
 * Begin(..., hard_A=4) preserves strict >4 A immediate protection.
 * No GPIO, fault clearing, output restart, allocation, or unbounded work.
 */
#define FOC_OC_CONFIRM_SOFT_A 4.0f
#define FOC_OC_CONFIRM_MAX_US 100U
typedef enum {
    FOC_OC_CLEAR, FOC_OC_PENDING, FOC_OC_TRIPPED
} FocOcConfirmResult;
typedef enum {
    FOC_OC_NONE, FOC_OC_HARD, FOC_OC_TWO_OF_THREE, FOC_OC_BAD_CONFIG,
    FOC_OC_BAD_SAMPLE, FOC_OC_GAP, FOC_OC_DEADLINE, FOC_OC_REPEATED_SINGLES
} FocOcConfirmReason;
typedef struct {
    float hard_A, count_to_A;
    uint16_t zero_u, zero_v;
} FocOcConfirmConfig;
typedef struct {
    FocOcConfirmConfig cfg;
    uint32_t last_seq, last_us, pending_us, single_window, singles;
    uint8_t ready, seq_valid, pending, misses, pending_mask, trip_mask;
    FocOcConfirmResult result;
    FocOcConfirmReason reason;
} FocOcConfirm;

static inline uint8_t FocOcConfirm_Finite(float v)
{ return v <= FLT_MAX && v >= -FLT_MAX; }
static inline FocOcConfirmResult FocOcConfirm_Trip(
    FocOcConfirm *s, FocOcConfirmReason reason, uint8_t mask)
{
    if (s->result != FOC_OC_TRIPPED) {
        s->reason=reason; s->trip_mask=mask;
        s->result=FOC_OC_TRIPPED;
    }
    return s->result; /* First cause sticky, including after later good samples. */
}
static inline FocOcConfirmResult FocOcConfirm_Begin(
    FocOcConfirm *s, FocOcConfirmConfig cfg)
{
    *s=(FocOcConfirm){0}; s->cfg=cfg;
    if (!FocOcConfirm_Finite(cfg.hard_A) || cfg.hard_A<FOC_OC_CONFIRM_SOFT_A ||
        !FocOcConfirm_Finite(cfg.count_to_A) || !(cfg.count_to_A>0.0f) ||
        cfg.zero_u>4095U || cfg.zero_v>4095U)
        return FocOcConfirm_Trip(s,FOC_OC_BAD_CONFIG,0U);
    s->ready=1U; return s->result;
}
static inline uint8_t FocOcConfirm_Mask(float u, float v, float w,
                                     float limit, uint8_t inclusive)
{
    if (inclusive)
        return (uint8_t)((u>=limit || u<=-limit) |
            ((v>=limit || v<=-limit)<<1U) | ((w>=limit || w<=-limit)<<2U));
    return (uint8_t)((u>limit || u<-limit) |
        ((v>limit || v<-limit)<<1U) | ((w>limit || w<-limit)<<2U));
}
/* Integration MUST call this from a bounded independent time source even if
 * ADC callbacks stop. No Push calls does NOT constitute two healthy samples.
 * Unsigned microsecond timestamps support wrap; calls must be <2^31 us apart.
 * This pure function itself is not a timer and cannot promise shutdown WCET.
 */
static inline FocOcConfirmResult FocOcConfirm_CheckDeadline(
    FocOcConfirm *s, uint32_t now_us)
{
    if (s->result==FOC_OC_TRIPPED) return s->result;
    if (!s->ready) return FocOcConfirm_Trip(s,FOC_OC_BAD_CONFIG,0U);
    if (s->pending && (uint32_t)(now_us-s->pending_us)>FOC_OC_CONFIRM_MAX_US)
        return FocOcConfirm_Trip(s,FOC_OC_DEADLINE,s->pending_mask);
    return s->result;
}
static inline FocOcConfirmResult FocOcConfirm_Push(
    FocOcConfirm *s, uint32_t seq, uint32_t now_us,
    uint16_t raw_u, uint16_t raw_v, uint8_t valid)
{
    if (s->result==FOC_OC_TRIPPED) return s->result;
    if (!s->ready) return FocOcConfirm_Trip(s,FOC_OC_BAD_CONFIG,0U);
    if (!valid || raw_u>4095U || raw_v>4095U)
        return FocOcConfirm_Trip(s,FOC_OC_BAD_SAMPLE,0U);
    float u=((int32_t)s->cfg.zero_u-raw_u)*s->cfg.count_to_A;
    float v=((int32_t)s->cfg.zero_v-raw_v)*s->cfg.count_to_A;
    float w=-(u+v);
    if (!FocOcConfirm_Finite(u) || !FocOcConfirm_Finite(v) ||
        !FocOcConfirm_Finite(w))
        return FocOcConfirm_Trip(s,FOC_OC_BAD_SAMPLE,0U);
    uint8_t hard=FocOcConfirm_Mask(u,v,w,s->cfg.hard_A,
        s->cfg.hard_A>FOC_OC_CONFIRM_SOFT_A);
    if (hard) return FocOcConfirm_Trip(s,FOC_OC_HARD,hard);
    if (FocOcConfirm_CheckDeadline(s,now_us)==FOC_OC_TRIPPED) return s->result;
    if (s->seq_valid && ((uint32_t)(seq-s->last_seq)!=1U ||
        (uint32_t)(now_us-s->last_us)==0U ||
        (uint32_t)(now_us-s->last_us)>FOC_OC_CONFIRM_MAX_US))
        return FocOcConfirm_Trip(s,FOC_OC_GAP,s->pending_mask);
    s->last_seq=seq; s->last_us=now_us; s->seq_valid=1U;
    s->single_window <<= 1U;
    uint8_t soft=FocOcConfirm_Mask(u,v,w,FOC_OC_CONFIRM_SOFT_A,0U);
    if (soft) {
        /* ANY two violating physical pairs in three samples. Cross-phase
         * hits also confirm; alternating phases cannot evade protection. */
        if (s->pending)
            return FocOcConfirm_Trip(s,FOC_OC_TWO_OF_THREE,
                                    (uint8_t)(s->pending_mask|soft));
        s->pending=1U; s->misses=0U; s->pending_us=now_us;
        s->pending_mask=soft; s->result=FOC_OC_PENDING;
    } else if (s->pending && ++s->misses>=2U) {
        s->pending=0U; s->misses=0U; s->pending_mask=0U;
        s->single_window |= 1U;
        if (s->singles!=UINT32_MAX) ++s->singles;
        s->result=FOC_OC_CLEAR;
        /* Provisional OFFLINE noise rule inherited from the observer:
         * three resolved singles per 32 samples. Not hardware qualified. */
        uint32_t bits=s->single_window;
        bits &= bits-1U; bits &= bits-1U;
        if (bits) return FocOcConfirm_Trip(s,FOC_OC_REPEATED_SINGLES,0U);
    }
    return s->result;
}
#endif
