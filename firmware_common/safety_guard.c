#include "safety_guard.h"
#include <stddef.h>
#include <string.h>

static void increment(uint32_t *value)
{
    if (*value != UINT32_MAX) ++*value;
}

void SafetySample_Reset(SafetySample *sample)
{
    if (sample != NULL) memset(sample, 0, sizeof(*sample));
}

void SafetySample_Update(SafetySample *sample, const uint16_t raw[3],
                         uint8_t acquisition_ok, uint32_t now_ms,
                         const SafetySamplePolicy *policy)
{
    uint16_t lo, hi;
    unsigned int i;
    if (sample == NULL) return;
    sample->acquisition_ok = 0U;
    if (raw == NULL || policy == NULL || acquisition_ok == 0U) {
        increment(&sample->failures);
        return; /* Failure never refreshes last successful sample. */
    }
    lo = hi = raw[0];
    for (i = 0U; i < 3U; ++i) {
        sample->raw[i] = raw[i];
        if (raw[i] < lo) lo = raw[i];
        if (raw[i] > hi) hi = raw[i];
    }
    sample->spread = (uint16_t)(hi - lo);
    sample->sampled_ms = now_ms;
    sample->seen = 1U;
    sample->acquisition_ok = 1U;
    if (sample->spread > policy->maximum_spread) increment(&sample->disagreements);
}

uint8_t SafetySample_Reasons(const SafetySample *sample,
                            const SafetySamplePolicy *policy, uint32_t now_ms)
{
    uint8_t reasons = 0U;
    unsigned int i;
    if (sample == NULL || policy == NULL) return 0x1fU;
    if (policy->calibrated_and_verified == 0U) reasons |= SAMPLE_UNQUALIFIED;
    if (sample->seen == 0U || sample->acquisition_ok == 0U) reasons |= SAMPLE_ACQUISITION;
    /* Unsigned subtraction supports one tick wrap; future timestamps fail closed. */
    if (sample->seen == 0U || (uint32_t)(now_ms - sample->sampled_ms) > SAFETY_FRESH_MS)
        reasons |= SAMPLE_STALE;
    if (policy->minimum_raw > policy->maximum_raw || policy->maximum_raw > 4095U)
        reasons |= SAMPLE_RANGE;
    if (sample->seen != 0U) {
        for (i = 0U; i < 3U; ++i)
            if (sample->raw[i] < policy->minimum_raw || sample->raw[i] > policy->maximum_raw)
                reasons |= SAMPLE_RANGE;
        if (sample->spread > policy->maximum_spread) reasons |= SAMPLE_DISAGREE;
    }
    return reasons;
}

uint16_t SafetyGuard_Missing(const SafetyEvidence *in,
                             uint8_t vbus_reasons, uint8_t temperature_reasons,
                             uint32_t now_ms)
{
    uint16_t mask = 0U;
    uint8_t feedback_fresh;
    if (in == NULL) return SAFETY_KNOWN_MASK;
    feedback_fresh = (uint32_t)(now_ms - in->feedback_ms) <= SAFETY_FRESH_MS;
    if (in->boot_locked) mask |= SAFETY_BOOT_LOCK;
    if (!feedback_fresh || !in->estop_verified_released) mask |= SAFETY_ESTOP;
    if (!feedback_fresh || !in->power_feedback_verified) mask |= SAFETY_POWER_FEEDBACK;
    if (!feedback_fresh || !in->current_verified) mask |= SAFETY_CURRENT;
    if (vbus_reasons != 0U) mask |= SAFETY_VBUS;
    if (temperature_reasons != 0U) mask |= SAFETY_TEMPERATURE;
    if (!feedback_fresh || !in->encoder_verified) mask |= SAFETY_ENCODER;
    if (!feedback_fresh || !in->link_verified) mask |= SAFETY_LINK;
    if (!in->firmware_confirmed) mask |= SAFETY_FIRMWARE;
    if (!in->recipe_verified) mask |= SAFETY_RECIPE;
    if (in->fault_latched) mask |= SAFETY_FAULT;
    return mask;
}

void SafetyGuard_EncodeLocked(uint16_t missing, uint8_t adc_ready,
                              uint8_t pc4_reasons, uint8_t pc5_reasons,
                              uint16_t sequence, uint8_t out[8])
{
    if (out == NULL) return;
    pc4_reasons &= 0x1fU;
    pc5_reasons &= 0x1fU;
    if (!adc_ready) {
        pc4_reasons |= SAMPLE_ACQUISITION;
        pc5_reasons |= SAMPLE_ACQUISITION;
    }
    missing = (uint16_t)((missing & SAFETY_KNOWN_MASK) | SAFETY_BOOT_LOCK);
    if (pc4_reasons) missing |= SAFETY_VBUS;
    if (pc5_reasons) missing |= SAFETY_TEMPERATURE;
    out[0] = 1U;
    out[1] = (uint8_t)(1U | (adc_ready ? 2U : 0U));
    out[2] = (uint8_t)missing; out[3] = (uint8_t)(missing >> 8);
    out[4] = (uint8_t)(pc4_reasons & 0x1fU);
    out[5] = (uint8_t)(pc5_reasons & 0x1fU);
    out[6] = (uint8_t)sequence; out[7] = (uint8_t)(sequence >> 8);
}

void SafetyGuard_EncodeRaw(const SafetySample *sample, uint16_t sequence, uint8_t out[8])
{
    unsigned int i;
    if (out == NULL) return;
    /* 0xffff denotes unavailable; never substitute old readings after a failed acquisition. */
    for (i = 0U; i < 3U; ++i) {
        uint16_t raw = (sample && sample->seen && sample->acquisition_ok) ? sample->raw[i] : UINT16_MAX;
        out[2U * i] = (uint8_t)raw; out[2U * i + 1U] = (uint8_t)(raw >> 8);
    }
    out[6] = (uint8_t)sequence; out[7] = (uint8_t)(sequence >> 8);
}
