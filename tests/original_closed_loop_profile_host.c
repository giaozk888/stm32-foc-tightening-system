#include "original_closed_loop_profile.h"
#include <assert.h>
#include <string.h>

int main(void)
{
    char text[256];
    int length = OriginalClosedLoop_FormatProfile(text, sizeof(text),
        (uint32_t)(FOC_CURRENT_TRIP_A * 1000.0f + 0.5f), RUN_ZERO_MAX_DELTA_COUNTS,
        (uint32_t)(FOC_TS_S * 1000000.0f + 0.5f),
        (uint32_t)(MOTOR_SPEED_IQ_LIMIT_A * 1000.0f + 0.5f),
        (uint32_t)(MOTOR_DIRECT_IQ_LIMIT_A * 1000.0f + 0.5f),
        (uint32_t)(FOC_VOLTAGE_LIMIT_V * 1000.0f + 0.5f));
    assert(length > 0 && (size_t)length < sizeof(text));
    assert(strstr(text, "TRIP_MA=4000 ZERO_DELTA=100 LOOP_US=50") != NULL);
    assert(strstr(text, "SPEED_IQ_MA=400 DIRECT_IQ_MA=150 VOLTAGE_MV=800") != NULL);
    assert(strstr(text, "FILTER=LEGACY_STEP_MEDIAN START=ORIGINAL QUALIFIED=0") != NULL);
    puts(text);
    char small[8];
    int required = OriginalClosedLoop_FormatProfile(small, sizeof(small), 4000, 100, 50, 400, 150, 800);
    assert(required == length && small[sizeof(small) - 1] == '\0');
    return 0;
}
