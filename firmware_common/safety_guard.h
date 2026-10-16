#ifndef SAFETY_GUARD_H
#define SAFETY_GUARD_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Diagnostic policy only; not a certified safety function or actuator API. */
#define SAFETY_REPORT_ID 0x184U
#define SAFETY_PC4_RAW_ID 0x185U
#define SAFETY_PC5_RAW_ID 0x186U
#define SAFETY_FRESH_MS 500U
enum {
    SAMPLE_UNQUALIFIED = 1U, SAMPLE_ACQUISITION = 2U,
    SAMPLE_RANGE = 4U, SAMPLE_DISAGREE = 8U, SAMPLE_STALE = 16U
};
typedef struct {
    uint16_t raw[3];
    uint16_t spread;
    uint32_t sampled_ms;
    uint32_t failures;
    uint32_t disagreements;
    uint8_t seen;
    uint8_t acquisition_ok;
} SafetySample;
typedef struct {
    uint16_t minimum_raw;
    uint16_t maximum_raw;
    uint16_t maximum_spread;
    uint8_t calibrated_and_verified;
} SafetySamplePolicy;
void SafetySample_Reset(SafetySample *sample);
void SafetySample_Update(SafetySample *sample, const uint16_t raw[3],
                         uint8_t acquisition_ok, uint32_t now_ms,
                         const SafetySamplePolicy *policy);
uint8_t SafetySample_Reasons(const SafetySample *sample,
                            const SafetySamplePolicy *policy, uint32_t now_ms);

enum {
    SAFETY_BOOT_LOCK = 1U << 0, SAFETY_ESTOP = 1U << 1,
    SAFETY_POWER_FEEDBACK = 1U << 2, SAFETY_CURRENT = 1U << 3,
    SAFETY_VBUS = 1U << 4, SAFETY_TEMPERATURE = 1U << 5,
    SAFETY_ENCODER = 1U << 6, SAFETY_LINK = 1U << 7,
    SAFETY_FIRMWARE = 1U << 8, SAFETY_RECIPE = 1U << 9,
    SAFETY_FAULT = 1U << 10, SAFETY_KNOWN_MASK = 0x7ffU
};
typedef struct {
    uint8_t boot_locked;
    uint8_t estop_verified_released;
    uint8_t power_feedback_verified;
    uint8_t current_verified;
    uint8_t encoder_verified;
    uint8_t link_verified;
    uint8_t firmware_confirmed;
    uint8_t recipe_verified;
    uint8_t fault_latched;
    /* Timestamp of independently verified feedback, NOT SD output/voltage estimate. */
    uint32_t feedback_ms;
} SafetyEvidence;
uint16_t SafetyGuard_Missing(const SafetyEvidence *evidence,
                             uint8_t vbus_reasons, uint8_t temperature_reasons,
                             uint32_t now_ms);
/* Locked report only. There is intentionally no unlock/control message. */
void SafetyGuard_EncodeLocked(uint16_t missing, uint8_t adc_ready,
                              uint8_t pc4_reasons, uint8_t pc5_reasons,
                              uint16_t sequence, uint8_t out[8]);
void SafetyGuard_EncodeRaw(const SafetySample *sample, uint16_t sequence,
                           uint8_t out[8]);
#ifdef __cplusplus
}
#endif
#endif
