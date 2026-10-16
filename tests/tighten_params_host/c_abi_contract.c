#include "tighten_params.h"

#include <assert.h>
#include <string.h>

/* This file is compiled as C11, not C++: proves the actual link boundary.
 * An independent original-layout fixture catches an accidental field reorder.
 */
typedef struct {
    uint32_t rundown_rpm, contact_rpm, contact_iq_mA, contact_ms;
    uint32_t rundown_timeout_ms, max_travel_deg;
    uint32_t seating_iq_mA, t1_iq_mA, t2_iq_mA, t3_iq_mA, hold_iq_mA;
    uint32_t seating_ms, t1_ms, t2_ms, t3_ms, hold_ms;
    uint32_t torque_abort_rpm, post_travel_max_deg;
} LegacyRecipe;

typedef struct {
    uint32_t magic, version, payload_size, reserved0;
    TightenParams_t params;
    uint32_t crc32, reserved1;
} LegacyFlashRecord;

_Static_assert(sizeof(LegacyFlashRecord) == 96U, "V1 record size");
_Static_assert(offsetof(LegacyFlashRecord, params) == 16U, "V1 payload offset");
_Static_assert(offsetof(LegacyFlashRecord, crc32) == 88U, "V1 CRC offset");

int c_abi_contract(void) {
    const LegacyRecipe original = {80U, 10U, 300U, 250U, 8000U, 3000U,
                                  80U, 100U, 120U, 150U, 150U,
                                  300U, 300U, 300U, 300U, 500U, 30U, 90U};
    TightenParams_t params = TIGHTEN_PARAMS_DEFAULT_INITIALIZER;
    uint32_t value = 0U;
    assert(sizeof(params) == sizeof(original));
    assert(memcmp(&params, &original, sizeof(params)) == 0);
    assert(TightenParams_Validate(&params) == 1U);
    assert(TightenParams_TryGet(&params, "RUNDOWN_RPM", &value) == TIGHTEN_PARAMS_OK);
    assert(value == 80U);
    assert(TightenParams_TrySet(&params, "RUNDOWN_RPM", 120U, 0U) == TIGHTEN_PARAMS_OK);
    assert(params.rundown_rpm == 120U);
    TightenParams_ResetDefaults(&params);
    assert(memcmp(&params, &original, sizeof(params)) == 0);
    return 1;
}
