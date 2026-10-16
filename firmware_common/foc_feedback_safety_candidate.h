#ifndef FOC_FEEDBACK_SAFETY_CANDIDATE_H
#define FOC_FEEDBACK_SAFETY_CANDIDATE_H
#include "foc_filtered_protection_candidate.h"
#include "foc_current_median.h"
#if defined(FOC_REPAIR_WINDOW_TRACE)
#include "foc_repair_trace.h"
#endif

/* Numerical selector/protection core: no motor admission, PWM writes or fault
 * clear. The hard-OFF binding remains hard-OFF. The separate protected motor
 * binding must verify its OWN output/session invariant; passing 1 here is not
 * hardware qualification or permission to enable an actuator. */
#if !defined(FOC_CURRENT_TREND4) || FOC_CURRENT_TREND4 != 1 || \
    !defined(FOC_CURRENT_SPIKE_ONLY) || FOC_CURRENT_SPIKE_ONLY != 1
#error Feedback safety candidate requires the four-point fixture filter
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC) && SWITCH_FEEDBACK_DIAGNOSTIC != 0
#error Feedback safety candidate cannot enable bridge switching
#endif

enum { FOC_FB_OUTPUT_LOCK_LOST = 16U };
typedef struct {
    FocFilteredProtectionConfig protection;
    uint16_t zero_u, zero_v;
    float count_to_A;
} FocFeedbackSafetyConfig;
typedef struct {
    uint32_t source_seq, source_us;
    float measurement_angle, actuation_angle;
    float iu_A, iv_A, iw_A;
    uint16_t u, v;
    uint8_t repaired_mask, ready;
} FocFeedbackFrame;
typedef struct {
    FocFeedbackSafetyConfig cfg;
    FocCurrentMedian filter;
    FocFilteredProtection protection;
    uint32_t seq[4], us[4];
    float angle[4];
    FocFeedbackFrame frame;
#if defined(FOC_REPAIR_WINDOW_TRACE)
    FocRepairTrace trace;
#endif
} FocFeedbackSafety;

/* Caller must serialize Push/Poll/Take. Begin is fixture initialization ONLY. */
static inline FocOcConfirmResult FocFeedbackSafety_Begin(
    FocFeedbackSafety *s, FocFeedbackSafetyConfig cfg, uint32_t now_us)
{
    *s = (FocFeedbackSafety){0};
    s->cfg = cfg;
    FocCurrentMedian_Begin(&s->filter);
    FocOcConfirmResult result = FocFp_Begin(&s->protection, cfg.protection, now_us);
    if (cfg.zero_u > 4095U || cfg.zero_v > 4095U ||
        !FocOcConfirm_Finite(cfg.count_to_A) || !(cfg.count_to_A > 0.0f))
        return FocFp_Trip(&s->protection, FOC_FP_CONFIG, 0U);
    return result;
}

/* Call from an independently scheduled fixture watchdog, including when ADC
 * stops. The invariant argument must come from the caller's output-register
 * check (hard-OFF for diagnostic callers; the separately bounded session for
 * the motor caller). It is not independent hardware shutdown verification. */
FOC_HOT_INLINE FocOcConfirmResult FocFeedbackSafety_Poll(
    FocFeedbackSafety *s, uint32_t now_us, uint32_t flags, uint8_t hard_off_verified)
{
    if (hard_off_verified != 1U) flags |= FOC_FB_OUTPUT_LOCK_LOST;
    FocOcConfirmResult result = FocFp_Poll(&s->protection, now_us, flags);
    if (result == FOC_OC_TRIPPED) s->frame.ready = 0U;
    return result;
}

/* Feed each PHYSICAL pair once. Input angle is the software angle estimate
 * associated with that callback, not proof of the encoder hardware timestamp.
 * No caller-supplied filtered sample can bypass the actual selector or its
 * repair accounting. Raw amplitude is NOT an overcurrent decision here. */
FOC_HOT_INLINE FocOcConfirmResult FocFeedbackSafety_Push(
    FocFeedbackSafety *s, uint32_t seq, uint32_t now_us,
    uint16_t raw_u, uint16_t raw_v, float angle,
    uint32_t flags, uint8_t hard_off_verified)
{
    s->frame.ready = 0U;
    if (FocFeedbackSafety_Poll(s, now_us, flags, hard_off_verified) == FOC_OC_TRIPPED)
        return s->protection.result;
    if (raw_u > 4095U || raw_v > 4095U)
        return FocFp_Trip(&s->protection, FOC_FP_RAW_INVALID, 0U);
    if (!FocOcConfirm_Finite(angle))
        return FocFp_Trip(&s->protection, FOC_FP_FEEDBACK_INVALID, 0U);

    uint8_t slot = s->filter.index;
    s->seq[slot] = seq; s->us[slot] = now_us; s->angle[slot] = angle;
    uint16_t u = 0U, v = 0U;
#if defined(FOC_REPAIR_WINDOW_TRACE)
    /* Capture adaptive bounds before quiet learning changes either estimator.
     * Analyze's strong-isolated branch may still use its fixed 40-count bound.
     * The trace never supplies replacement data. */
    uint16_t jump_u=FocAdaptive_Jump(&s->filter.noise[0]);
    uint16_t jump_v=FocAdaptive_Jump(&s->filter.noise[1]);
#endif
    uint8_t ready = (uint8_t)FocCurrentMedian_Push(&s->filter, raw_u, raw_v, &u, &v);
#if defined(FOC_REPAIR_WINDOW_TRACE)
    FocRepairTrace_Record(&s->trace,seq,now_us,raw_u,raw_v,u,v,ready,
        s->filter.last_spike_mask,jump_u,jump_v);
#endif
    uint8_t center = (uint8_t)((s->filter.index + 2U) % 4U);
    float iu = ready ? ((int32_t)s->cfg.zero_u - (int32_t)u)*s->cfg.count_to_A : 0.0f;
    float iv = ready ? ((int32_t)s->cfg.zero_v - (int32_t)v)*s->cfg.count_to_A : 0.0f;
    FocOcConfirmResult result =
#if defined(FOC_GUARD_FAST_PATH)
        /* The Poll above checked the same timestamp/flags and the caller
         * serializes the whole Push. Keep the later Take recheck intact. */
        FocFp_PushAfterPoll(
#else
        FocFp_Push(
#endif
        &s->protection, seq, now_us, raw_u, raw_v, ready,
        s->seq[center], iu, iv, s->filter.last_spike_mask, 0U);
    if (ready && result != FOC_OC_TRIPPED) {
        s->frame = (FocFeedbackFrame){
            .source_seq = s->seq[center], .source_us = s->us[center],
            .measurement_angle = s->angle[center], .actuation_angle = angle,
            .iu_A = iu, .iv_A = iv, .iw_A = -(iu + iv),
            .u = u, .v = v, .repaired_mask = s->filter.last_spike_mask, .ready = 1U
        };
    }
    return result;
}

/* At most one consumption per Push. Recheck freshness and health at consumption,
 * not only at publication. Independent Poll is still required if both producer
 * and consumer stop. A valid frame permits fixture COMPUTATION only, never
 * bridge/motor activation by itself. Failure also clears caller's old frame. */
FOC_HOT_INLINE int FocFeedbackSafety_Take(
    FocFeedbackSafety *s, uint32_t now_us, uint32_t flags,
    uint8_t hard_off_verified, FocFeedbackFrame *out)
{
    *out = (FocFeedbackFrame){0};
    if (FocFeedbackSafety_Poll(s, now_us, flags, hard_off_verified) == FOC_OC_TRIPPED ||
        !s->frame.ready) return 0;
    *out = s->frame;
    s->frame.ready = 0U;
    return 1;
}
#endif
