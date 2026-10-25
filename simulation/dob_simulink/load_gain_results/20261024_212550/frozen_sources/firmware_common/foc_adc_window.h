#ifndef FOC_ADC_WINDOW_H
#define FOC_ADC_WINDOW_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Integer timer geometry, not a certification of the analog front end. */
typedef enum {
    FOC_SENSE_UNCONFIRMED = 0,
    FOC_SENSE_INLINE = 1,
    FOC_SENSE_LOW_SIDE_UV = 2
} FocSenseTopology;
typedef enum {
    FOC_WINDOW_OK = 0,
    FOC_WINDOW_TOPOLOGY_UNKNOWN,
    FOC_WINDOW_BAD_ARGUMENT,
    FOC_WINDOW_TOO_SHORT
} FocWindowStatus;
typedef enum {
    FOC_SAMPLE_WINDOW_MIDPOINT = 0,
    /* RC diagnostic only: maximize low-side observation time, but finish
     * the sampling aperture before the peak preload/update boundary. */
    FOC_SAMPLE_LATE_BEFORE_PEAK = 1
} FocSamplePlacement;
typedef struct {
    uint16_t arr;
    uint16_t dead_ticks;
    uint16_t settle_ticks;  /* measured driver/amplifier settling + margin */
    uint16_t latency_ticks; /* upper bound, trigger -> sampling start */
    uint16_t aperture_ticks;
    FocSenseTopology topology;
    uint16_t min_low_on_ticks; /* after dead time; not an analog certification */
    FocSamplePlacement placement;
} FocWindowConfig;
typedef struct {
    uint16_t phase[3];
    uint16_t trigger;
    uint16_t earliest;
    uint16_t latest;
    uint16_t slack_ticks;
} FocWindowPlan;

/* PWM2 CH4 rising edge exists only on the upward count. The sampling aperture
 * may cross the peak if it still fits between guarded switching edges.
 * LOW_SIDE_UV additionally requires both U/V low-side reference states.
 * All three phase edges are excluded, including W's interference edge. */
FocWindowStatus FocAdcWindow_Plan(const FocWindowConfig *config,
                                const uint16_t phase[3], FocWindowPlan *plan);
/* Reference duty limit, not physical high-side duty after dead-time. */
FocWindowStatus FocAdcWindow_Duty(const FocWindowConfig *config,
                                float u, float v, float w, FocWindowPlan *plan);

/* Bounded raw spread statistics, not measurement of analog switching noise
 * unless the input/load/supply/temperature are held constant externally. */
#define FOC_SPREAD_BLOCK 256U
typedef struct {
    uint32_t count, sum[2], sum_sq[2];
    uint16_t min[2], max[2], max_step[2], previous[2];
} FocRawSpread;
void FocRawSpread_Reset(FocRawSpread *spread);
void FocRawSpread_Push(FocRawSpread *spread, uint16_t u, uint16_t v);
#ifdef __cplusplus
}
#endif
#endif
