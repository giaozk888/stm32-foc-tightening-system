#ifndef FOC_FILTERED_PROTECTION_CANDIDATE_H
#define FOC_FILTERED_PROTECTION_CANDIDATE_H
#include "foc_overcurrent_confirm.h"
#include "foc_hot_path.h"

/* OFFLINE / HARD-OFF / bounded disconnected-bridge CANDIDATE,
 * NOT a motor-control protection qualification.
 * Hardware must autonomously shut down power; flags only record its indication.
 * No software severe-current threshold, GPIO, runtime bypass, or auto-restart.
 * One serialized owner must Push EVERY physical pair and independently Poll
 * when ADC callbacks stop. Neither function implements an actual timer/stop.
 */
#if !(defined(FOC_PROTECTION_HOST_TEST) && FOC_PROTECTION_HOST_TEST == 1) && \
    !(defined(FOC_PROTECTED_CLOSED_LOOP) && FOC_PROTECTED_CLOSED_LOOP == 1) && \
    !(defined(FOC_ISOLATED_CONCURRENCY) && FOC_ISOLATED_CONCURRENCY == 1 && \
      defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY) && FOC_ZERO_MEDIAN_COMPUTE_ONLY == 1) && \
    !(defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC) && SWITCH_FILTERED_BRIDGE_DIAGNOSTIC == 1 && \
      defined(SWITCH_FEEDBACK_DIAGNOSTIC) && SWITCH_FEEDBACK_DIAGNOSTIC == 1 && \
      defined(ZERO_RETEST_BOOT) && ZERO_RETEST_BOOT == 1 && \
      defined(ZERO_MEDIAN_DIAGNOSTIC) && ZERO_MEDIAN_DIAGNOSTIC == 1 && \
      !defined(SWITCH_SIGNAL_ONLY_DIAGNOSTIC))
#error Filtered protection requires an explicitly isolated fixture
#endif

enum { FOC_FP_HW_TRIP=1U, FOC_FP_DRIVER_FAULT=2U,
       FOC_FP_ADC_INVALID=4U, FOC_FP_ZERO_INVALID=8U };
typedef enum {
    FOC_FP_NONE, FOC_FP_CONFIG, FOC_FP_HARDWARE, FOC_FP_HEALTH,
    FOC_FP_RAW_INVALID, FOC_FP_SEQUENCE, FOC_FP_TIMEOUT,
    FOC_FP_FEEDBACK_INVALID, FOC_FP_FEEDBACK_MISSING,
    FOC_FP_REPAIR_BUDGET, FOC_FP_CONFIRMED_CURRENT
} FocFilteredProtectionReason;
typedef struct {
    float soft_A;
    uint32_t sample_deadline_us, confirm_deadline_us;
    uint8_t repair_hits_per_32, repair_streak;
} FocFilteredProtectionConfig;
typedef struct {
    FocFilteredProtectionConfig cfg;
    uint32_t begin_us, last_us, last_seq, pending_us, fault_flags;
    uint32_t repair_window, raw_pairs, feedback_pairs, repaired_pairs;
    uint8_t initialized, seq_valid, feedback_valid, warmup_pairs;
    uint8_t pending, misses, pending_mask, trip_mask, repair_streak;
    FocOcConfirmResult result;
    FocFilteredProtectionReason reason;
} FocFilteredProtection;

FOC_HOT_INLINE FocOcConfirmResult FocFp_Trip(
    FocFilteredProtection *s, FocFilteredProtectionReason reason, uint8_t mask)
{
    if (s->result!=FOC_OC_TRIPPED) {
        s->result=FOC_OC_TRIPPED; s->reason=reason; s->trip_mask=mask;
    }
    return s->result;
}
/* Begin is explicit fixture initialization, not an automatic fault-clear API. */
static inline FocOcConfirmResult FocFp_Begin(
    FocFilteredProtection *s, FocFilteredProtectionConfig cfg, uint32_t now_us)
{
    *s=(FocFilteredProtection){0}; s->cfg=cfg; s->begin_us=now_us;
    if (!FocOcConfirm_Finite(cfg.soft_A) || !(cfg.soft_A>0.0f) ||
        !cfg.sample_deadline_us || cfg.sample_deadline_us>INT32_MAX ||
        !cfg.confirm_deadline_us || cfg.confirm_deadline_us>INT32_MAX ||
        !cfg.repair_hits_per_32 || cfg.repair_hits_per_32>32U ||
        !cfg.repair_streak || cfg.repair_streak>32U)
        return FocFp_Trip(s,FOC_FP_CONFIG,0U);
    s->initialized=1U; return s->result;
}
FOC_HOT_INLINE FocOcConfirmResult FocFp_Poll(
    FocFilteredProtection *s, uint32_t now_us, uint32_t flags)
{
    s->fault_flags|=flags;
    if (s->result==FOC_OC_TRIPPED) return s->result;
    if (!s->initialized) return FocFp_Trip(s,FOC_FP_CONFIG,0U);
    if (flags&(FOC_FP_HW_TRIP|FOC_FP_DRIVER_FAULT))
        return FocFp_Trip(s,FOC_FP_HARDWARE,0U);
    if (flags) return FocFp_Trip(s,FOC_FP_HEALTH,0U); /* unknown bits fail closed */
    uint32_t since=s->seq_valid?s->last_us:s->begin_us;
    if ((uint32_t)(now_us-since)>s->cfg.sample_deadline_us ||
        (s->pending && (uint32_t)(now_us-s->pending_us)>s->cfg.confirm_deadline_us))
        return FocFp_Trip(s,FOC_FP_TIMEOUT,s->pending_mask);
    return s->result;
}
static inline void FocFp_Increment(uint32_t *value)
{ if (*value!=UINT32_MAX) ++*value; }
static inline uint8_t FocFp_Popcount(uint32_t bits)
{
#if defined(FOC_PAIR_FAST_PATH)
    /* Fixed SWAR reduction: identical 32-bit population count without a loop
     * or compiler popcount helper call on Cortex-M4. No cached state to drift. */
    bits -= (bits >> 1U) & UINT32_C(0x55555555);
    bits = (bits & UINT32_C(0x33333333)) + ((bits >> 2U) & UINT32_C(0x33333333));
    bits = (bits + (bits >> 4U)) & UINT32_C(0x0f0f0f0f);
    bits += bits >> 8U;
    bits += bits >> 16U;
    return (uint8_t)(bits & 0x3fU);
#else
    uint8_t count=0U;
    /* Exactly 32 iterations; no data-dependent/unbounded work. */
    for (unsigned i=0U;i<32U;++i) count+=(uint8_t)((bits>>i)&1U);
    return count;
#endif
}
/* Raw is checked for validity/continuity, NOT current amplitude. FOC feedback
 * is the four-point filter's center output, exactly one physical pair old.
 * Caller supplies the source sequence and repaired mask (U=1,V=2).
 * Missing feedback is permitted only for the first three warm-up pairs.
 */
FOC_HOT_INLINE FocOcConfirmResult
#if defined(FOC_GUARD_FAST_PATH)
FocFp_PushAfterPoll(
#else
FocFp_Push(
#endif
    FocFilteredProtection *s, uint32_t seq, uint32_t now_us,
    uint16_t raw_u, uint16_t raw_v, uint8_t feedback_ready,
    uint32_t feedback_seq, float filtered_u_A, float filtered_v_A,
    uint8_t repaired_mask, uint32_t flags)
{
#if defined(FOC_GUARD_FAST_PATH)
    /* Internal only: serialized caller has just performed FocFp_Poll with
     * this exact now/flags, without any intervening shared-state writer. */
    (void)flags;
#else
    if (FocFp_Poll(s,now_us,flags)==FOC_OC_TRIPPED) return s->result;
#endif
    if (raw_u>4095U || raw_v>4095U)
        return FocFp_Trip(s,FOC_FP_RAW_INVALID,0U);
    if (feedback_ready>1U)
        return FocFp_Trip(s,FOC_FP_FEEDBACK_INVALID,0U);
    if (s->seq_valid && ((uint32_t)(seq-s->last_seq)!=1U || now_us==s->last_us))
        return FocFp_Trip(s,FOC_FP_SEQUENCE,0U);
    s->last_seq=seq; s->last_us=now_us; s->seq_valid=1U;
    FocFp_Increment(&s->raw_pairs);
    if (s->warmup_pairs<4U) ++s->warmup_pairs;
    if (!feedback_ready) {
        if (s->feedback_valid || s->warmup_pairs>=4U)
            return FocFp_Trip(s,FOC_FP_FEEDBACK_MISSING,0U);
        return s->result;
    }
    if (s->warmup_pairs<4U || (uint32_t)(seq-feedback_seq)!=1U ||
        repaired_mask>3U || !FocOcConfirm_Finite(filtered_u_A) ||
        !FocOcConfirm_Finite(filtered_v_A))
        return FocFp_Trip(s,FOC_FP_FEEDBACK_INVALID,0U);
    float w=-(filtered_u_A+filtered_v_A);
    if (!FocOcConfirm_Finite(w))
        return FocFp_Trip(s,FOC_FP_FEEDBACK_INVALID,0U);
    s->feedback_valid=1U; FocFp_Increment(&s->feedback_pairs);
    s->repair_window=(s->repair_window<<1U)|(repaired_mask?1U:0U);
    s->repair_streak=repaired_mask?(uint8_t)(s->repair_streak+1U):0U;
    if (repaired_mask) FocFp_Increment(&s->repaired_pairs);
    if (s->repair_streak>s->cfg.repair_streak ||
        FocFp_Popcount(s->repair_window)>s->cfg.repair_hits_per_32)
        return FocFp_Trip(s,FOC_FP_REPAIR_BUDGET,0U);
    uint8_t mask=FocOcConfirm_Mask(filtered_u_A,filtered_v_A,w,s->cfg.soft_A,0U);
    if (mask) {
        if (s->pending)
            return FocFp_Trip(s,FOC_FP_CONFIRMED_CURRENT,(uint8_t)(s->pending_mask|mask));
        s->pending=1U; s->misses=0U; s->pending_us=now_us;
        s->pending_mask=mask; s->result=FOC_OC_PENDING;
    } else if (s->pending && ++s->misses>=2U) {
        s->pending=0U; s->misses=0U; s->pending_mask=0U; s->result=FOC_OC_CLEAR;
    }
    return s->result;
}
#if defined(FOC_GUARD_FAST_PATH)
/* Public entry always checks deadlines/health. Never expose the internal
 * post-poll step as a way to feed unverified samples. */
FOC_HOT_INLINE FocOcConfirmResult FocFp_Push(
    FocFilteredProtection *s, uint32_t seq, uint32_t now_us,
    uint16_t raw_u, uint16_t raw_v, uint8_t feedback_ready,
    uint32_t feedback_seq, float filtered_u_A, float filtered_v_A,
    uint8_t repaired_mask, uint32_t flags)
{
    if (FocFp_Poll(s,now_us,flags)==FOC_OC_TRIPPED) return s->result;
    return FocFp_PushAfterPoll(s,seq,now_us,raw_u,raw_v,feedback_ready,
        feedback_seq,filtered_u_A,filtered_v_A,repaired_mask,flags);
}
#endif
#endif
