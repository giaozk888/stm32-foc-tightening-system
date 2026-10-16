#include "safety_guard.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stddef.h>
#include <stdio.h>

int main(void)
{
    SafetySample sample;
    SafetySamplePolicy policy = {0U, 4095U, 60U, 0U};
    SafetyEvidence in = {0};
    uint16_t clean[3] = {600U, 600U, 600U};
    uint16_t spike[3] = {600U, 600U, 1400U};
    uint16_t bad_median[3] = {752U, 576U, 778U};
    uint16_t invalid[3] = {4096U, 4096U, 4096U};
    uint8_t data[8];
    SafetySample_Reset(&sample);
    assert(SafetySample_Reasons(&sample, &policy, 0U) ==
           (SAMPLE_UNQUALIFIED | SAMPLE_ACQUISITION | SAMPLE_STALE));
    SafetySample_Update(&sample, clean, 1U, 100U, &policy);
    assert(SafetySample_Reasons(&sample, &policy, 600U) == SAMPLE_UNQUALIFIED);
    assert(SafetySample_Reasons(&sample, &policy, 601U) == (SAMPLE_UNQUALIFIED | SAMPLE_STALE));
    /* Even perfectly stable raw readings are not proof of physical calibration. */
    policy.calibrated_and_verified = 1U; /* Synthetic fixture only. */
    assert(SafetySample_Reasons(&sample, &policy, 600U) == 0U);
    SafetySample_Update(&sample, spike, 1U, 700U, &policy);
    assert(SafetySample_Reasons(&sample, &policy, 700U) == SAMPLE_DISAGREE);
    SafetySample_Update(&sample, bad_median, 1U, 800U, &policy);
    assert(SafetySample_Reasons(&sample, &policy, 800U) == SAMPLE_DISAGREE);
    assert(sample.disagreements == 2U);
    SafetySample_Update(&sample, invalid, 1U, 900U, &policy);
    assert(SafetySample_Reasons(&sample, &policy, 900U) == SAMPLE_RANGE);
    SafetySample_Update(&sample, clean, 0U, 1000U, &policy);
    assert(sample.sampled_ms == 900U && sample.failures == 1U);
    assert((SafetySample_Reasons(&sample, &policy, 1000U) & SAMPLE_ACQUISITION) != 0U);
    SafetyGuard_EncodeRaw(&sample, 7U, data);
    assert(data[0] == 255U && data[5] == 255U && data[6] == 7U);
    SafetySample_Update(&sample, clean, 1U, UINT32_MAX - 9U, &policy);
    assert(SafetySample_Reasons(&sample, &policy, 10U) == 0U);
    assert((SafetySample_Reasons(&sample, &policy, UINT32_MAX - 10U) & SAMPLE_STALE) != 0U);
    policy.minimum_raw = 1000U; policy.maximum_raw = 999U;
    assert((SafetySample_Reasons(&sample, &policy, 10U) & SAMPLE_RANGE) != 0U);
    sample.failures = UINT32_MAX;
    SafetySample_Update(&sample, NULL, 0U, 20U, &policy);
    assert(sample.failures == UINT32_MAX);
    assert(SafetySample_Reasons(NULL, &policy, 0U) == 0x1fU);
    assert(SafetyGuard_Missing(NULL, 0U, 0U, 0U) == SAFETY_KNOWN_MASK);
    in.boot_locked = 1U;
    assert(SafetyGuard_Missing(&in, 1U, 1U, 0U) == (SAFETY_KNOWN_MASK & ~SAFETY_FAULT));
    /* Exhaustive synthetic evidence combinations, including each independent missing input. */
    for (unsigned int bits = 0U; bits < 256U; ++bits) {
        in.boot_locked = 0U;
        in.estop_verified_released = (bits & 1U) != 0U;
        in.power_feedback_verified = (bits & 2U) != 0U;
        in.current_verified = (bits & 4U) != 0U;
        in.encoder_verified = (bits & 8U) != 0U;
        in.link_verified = (bits & 16U) != 0U;
        in.firmware_confirmed = (bits & 32U) != 0U;
        in.recipe_verified = (bits & 64U) != 0U;
        in.fault_latched = (bits & 128U) == 0U;
        in.feedback_ms = 100U;
        uint16_t mask = SafetyGuard_Missing(&in, 0U, 0U, 600U);
        assert(((mask & SAFETY_ESTOP) == 0U) == (in.estop_verified_released != 0U));
        assert(((mask & SAFETY_POWER_FEEDBACK) == 0U) == (in.power_feedback_verified != 0U));
        assert(((mask & SAFETY_CURRENT) == 0U) == (in.current_verified != 0U));
        assert(((mask & SAFETY_ENCODER) == 0U) == (in.encoder_verified != 0U));
        assert(((mask & SAFETY_LINK) == 0U) == (in.link_verified != 0U));
        assert(((mask & SAFETY_FIRMWARE) == 0U) == (in.firmware_confirmed != 0U));
        assert(((mask & SAFETY_RECIPE) == 0U) == (in.recipe_verified != 0U));
        assert(((mask & SAFETY_FAULT) == 0U) == (in.fault_latched == 0U));
        assert((SafetyGuard_Missing(&in, 0U, 0U, 601U) &
                (SAFETY_ESTOP | SAFETY_POWER_FEEDBACK | SAFETY_CURRENT | SAFETY_ENCODER | SAFETY_LINK)) ==
               (SAFETY_ESTOP | SAFETY_POWER_FEEDBACK | SAFETY_CURRENT | SAFETY_ENCODER | SAFETY_LINK));
    }
    SafetyGuard_EncodeLocked(0U, 1U, 1U, 1U, 0x1234U, data);
    assert(data[0] == 1U && data[1] == 3U &&
           data[2] == (SAFETY_BOOT_LOCK | SAFETY_VBUS | SAFETY_TEMPERATURE));
    assert(data[6] == 0x34U && data[7] == 0x12U);
    SafetyGuard_EncodeLocked(0U, 0U, 0U, 0U, 0U, data);
    assert(data[1] == 1U && data[4] == SAMPLE_ACQUISITION && data[5] == SAMPLE_ACQUISITION);
    puts("safety_guard: sample faults, freshness/wrap, 256 interlock combinations PASS");
    return 0;
}
