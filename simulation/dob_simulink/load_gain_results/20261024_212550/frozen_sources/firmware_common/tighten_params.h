#ifndef TIGHTEN_PARAMS_H
#define TIGHTEN_PARAMS_H

#include <stddef.h>
#include <stdint.h>
#include "foc_rundown240_candidate.h"

/* Normal V1 field order, integer units, limits and defaults are persistent ABI.
 * Do not reorder or widen fields: existing Flash/KVS records contain these
 * exact 18 uint32_t values. Changes require a versioned storage migration.
 * X(field, wire_name, minimum, maximum, default_value)
 */
#if defined(FOC_RUNDOWN240_CANDIDATE)
/* RAM-only A experiment. StorageSave is disabled, including legacy migration;
 * the shared V1 record layout and the fallback's limits remain unchanged. */
#define TIGHTEN_RUNDOWN_DEFAULT_RPM FOC_RUNDOWN240_TARGET_RPM
#define TIGHTEN_RUNDOWN_MAX_RPM FOC_RUNDOWN240_TARGET_RPM
#elif defined(TIGHTEN_SPEED_X2_OFFLINE)
/* Output-locked, opt-in experiment only. StorageSave is disabled for this
 * profile so its extended range cannot invalidate a normal fallback recipe.
 * Existing KVS values are loaded unchanged; they are NOT multiplied on boot.
 */
#define TIGHTEN_RUNDOWN_DEFAULT_RPM 160U
#define TIGHTEN_RUNDOWN_MAX_RPM 240U
#else
#define TIGHTEN_RUNDOWN_DEFAULT_RPM 80U
#define TIGHTEN_RUNDOWN_MAX_RPM 120U
#endif

#if defined(FOC_RUNDOWN240_TRAVEL20000)
#define TIGHTEN_MAX_TRAVEL_LIMIT_DEG FOC_RUNDOWN240_MAX_TRAVEL_DEG
#define TIGHTEN_MAX_TRAVEL_DEFAULT_DEG FOC_RUNDOWN240_MAX_TRAVEL_DEG
#else
#define TIGHTEN_MAX_TRAVEL_LIMIT_DEG 10000U
#define TIGHTEN_MAX_TRAVEL_DEFAULT_DEG 3000U
#endif

#define TIGHTEN_PARAM_FIELDS(X) \
    X(rundown_rpm, "RUNDOWN_RPM", 20U, TIGHTEN_RUNDOWN_MAX_RPM, TIGHTEN_RUNDOWN_DEFAULT_RPM) \
    X(contact_rpm, "CONTACT_RPM", 1U, 20U, 10U) \
    X(contact_iq_mA, "CONTACT_IQ_MA", 100U, 400U, 300U) \
    X(contact_ms, "CONTACT_MS", 50U, 1000U, 250U) \
    X(rundown_timeout_ms, "RUNDOWN_TIMEOUT_MS", 1000U, 20000U, 8000U) \
    X(max_travel_deg, "MAX_TRAVEL_DEG", 100U, TIGHTEN_MAX_TRAVEL_LIMIT_DEG, TIGHTEN_MAX_TRAVEL_DEFAULT_DEG) \
    X(seating_iq_mA, "SEATING_IQ_MA", 20U, 150U, 80U) \
    X(t1_iq_mA, "T1_IQ_MA", 20U, 150U, 100U) \
    X(t2_iq_mA, "T2_IQ_MA", 20U, 150U, 120U) \
    X(t3_iq_mA, "T3_IQ_MA", 20U, 150U, 150U) \
    X(hold_iq_mA, "HOLD_IQ_MA", 20U, 150U, 150U) \
    X(seating_ms, "SEATING_MS", 50U, 2000U, 300U) \
    X(t1_ms, "T1_MS", 50U, 2000U, 300U) \
    X(t2_ms, "T2_MS", 50U, 2000U, 300U) \
    X(t3_ms, "T3_MS", 50U, 2000U, 300U) \
    X(hold_ms, "HOLD_MS", 50U, 3000U, 500U) \
    X(torque_abort_rpm, "TORQUE_ABORT_RPM", 5U, 100U, 30U) \
    X(post_travel_max_deg, "POST_TRAVEL_MAX_DEG", 5U, 360U, 90U)

#define TIGHTEN_PARAM_DECLARE(field, name, low, high, initial) uint32_t field;
typedef struct {
    TIGHTEN_PARAM_FIELDS(TIGHTEN_PARAM_DECLARE)
} TightenParams_t;
#undef TIGHTEN_PARAM_DECLARE

#define TIGHTEN_PARAM_INITIAL(field, name, low, high, initial) initial,
#define TIGHTEN_PARAMS_DEFAULT_INITIALIZER \
    { TIGHTEN_PARAM_FIELDS(TIGHTEN_PARAM_INITIAL) }

typedef enum {
    TIGHTEN_PARAMS_OK = 0,
    TIGHTEN_PARAMS_INVALID_ARGUMENT,
    TIGHTEN_PARAMS_UNKNOWN_NAME,
    TIGHTEN_PARAMS_OUT_OF_RANGE,
    TIGHTEN_PARAMS_BUSY
} TightenParamsResult_t;

#ifdef __cplusplus
static_assert(sizeof(TightenParams_t) == 72U, "V1 recipe size changed");
static_assert(offsetof(TightenParams_t, post_travel_max_deg) == 68U,
              "V1 recipe layout changed");
extern "C" {
#else
_Static_assert(sizeof(TightenParams_t) == 72U, "V1 recipe size changed");
_Static_assert(offsetof(TightenParams_t, post_travel_max_deg) == 68U,
               "V1 recipe layout changed");
#endif

/* C ABI, C++17 implementation. No HAL/RTOS dependency or allocation.
 * Caller owns the recipe and serialization: NOT an ISR/concurrency lock.
 * Busy guard has priority, matching the existing protocol. Any rejected SET
 * leaves the entire record unchanged. Names are uppercase after C parsing.
 */
uint8_t TightenParams_Validate(const TightenParams_t *params);
void TightenParams_ResetDefaults(TightenParams_t *params);
TightenParamsResult_t TightenParams_TryGet(const TightenParams_t *params,
                                        const char *name, uint32_t *value);
TightenParamsResult_t TightenParams_TrySet(TightenParams_t *params,
                                        const char *name, uint32_t value,
                                        uint8_t busy);

#ifdef __cplusplus
}
#endif
#endif
