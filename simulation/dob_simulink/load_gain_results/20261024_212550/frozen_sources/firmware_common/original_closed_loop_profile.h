#ifndef ORIGINAL_CLOSED_LOOP_PROFILE_H
#define ORIGINAL_CLOSED_LOOP_PROFILE_H

#include <stdint.h>
#include <stdio.h>

/* Boot-only reporting: arguments come from the actual control macros, not
 * separately hard-coded banner values. No ISR or motion admission changes. */
static inline int OriginalClosedLoop_FormatProfile(char *out, size_t size,
    uint32_t trip_ma, uint32_t zero_delta, uint32_t loop_us,
    uint32_t speed_iq_ma, uint32_t direct_iq_ma, uint32_t voltage_mv)
{
    return snprintf(out, size,
        "CONTROL PROFILE: ORIGINAL_UPDATED_20261015 TRIP_MA=%lu ZERO_DELTA=%lu "
        "LOOP_US=%lu SPEED_IQ_MA=%lu DIRECT_IQ_MA=%lu VOLTAGE_MV=%lu "
        "FILTER=LEGACY_STEP_MEDIAN START=ORIGINAL QUALIFIED=0\r\n",
        (unsigned long)trip_ma, (unsigned long)zero_delta, (unsigned long)loop_us,
        (unsigned long)speed_iq_ma, (unsigned long)direct_iq_ma, (unsigned long)voltage_mv);
}

#endif
