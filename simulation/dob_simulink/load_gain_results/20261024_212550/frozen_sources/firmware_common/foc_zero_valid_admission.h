#ifndef FOC_ZERO_VALID_ADMISSION_H
#define FOC_ZERO_VALID_ADMISSION_H
#include "foc_current_zero.h"
/* Collection counts exclude the unchanged 20000-pair settling interval.
 * Observed: 43/3125 rejected pairs (1.38%). 80/4000 is a provisional 2%
 * rejection budget, not an unlimited outlier mask. */
#ifndef ZERO_CAL_VALID_TARGET
#define ZERO_CAL_VALID_TARGET 4000U
#endif
#ifndef ZERO_CAL_MAX_TOTAL_SAMPLES
#define ZERO_CAL_MAX_TOTAL_SAMPLES 4100U
#endif
#ifndef ZERO_CAL_MAX_REJECT_COUNT
#define ZERO_CAL_MAX_REJECT_COUNT 80U
#endif
#ifndef ZERO_CAL_MAX_CONSEC_REJECT
#define ZERO_CAL_MAX_CONSEC_REJECT 2U
#endif
_Static_assert(ZERO_CAL_VALID_TARGET==FOC_ZERO_WINDOW_PAIRS,"Keep the 4000-valid target");
_Static_assert(ZERO_CAL_MAX_TOTAL_SAMPLES>=ZERO_CAL_VALID_TARGET,"Total budget below target");
_Static_assert(ZERO_CAL_MAX_TOTAL_SAMPLES<=UINT32_MAX/4095U,"Zero sum/count overflow");
#endif
