#ifndef FOC_CURRENT_SPIKE_H
#define FOC_CURRENT_SPIKE_H
#include <stdint.h>

/* Chronological a,b,c. Only an isolated CENTER extremum can be rejected.
 * Normal centers, ramps, sustained steps and two-sample bursts are unchanged.
 * Independent endpoint/jump thresholds; these are feedback-filter settings,
 * not current protection limits. The caller keeps the one-pair delay.
 * Invalid 12-bit codes are NEVER hidden by this feedback-only primitive.
 */
#define FOC_SPIKE3_ENDPOINT_COUNTS 10U
#define FOC_SPIKE3_JUMP_COUNTS 40U
#define FOC_SPIKE3_FILTER_REV 2U
static inline uint32_t FocSpike3_Distance(uint16_t a, uint16_t b)
{ return a > b ? (uint32_t)a-b : (uint32_t)b-a; }
static inline uint8_t FocSpike3_Isolated(uint16_t a, uint16_t b, uint16_t c)
{
    return a <= 4095U && b <= 4095U && c <= 4095U &&
        FocSpike3_Distance(a,c) <= FOC_SPIKE3_ENDPOINT_COUNTS &&
        FocSpike3_Distance(a,b) > FOC_SPIKE3_JUMP_COUNTS &&
        FocSpike3_Distance(b,c) > FOC_SPIKE3_JUMP_COUNTS &&
        ((b > a && b > c) || (b < a && b < c));
}
static inline uint16_t FocSpike3_Select(uint16_t a, uint16_t b, uint16_t c)
{
    /* Interpolate only the marked center; round half counts upward.
     * Preserve all physical samples in the separate diagnostic history. */
    return FocSpike3_Isolated(a,b,c) ? (uint16_t)(((uint32_t)a+c+1U)/2U) : b;
}
#endif
