#ifndef FOC_PWM_COMMON_MODE_H
#define FOC_PWM_COMMON_MODE_H
#include "foc_adc_window.h"

/* Additional DIGITAL headroom, never a replacement for dead/settle/RC time.
 * 85 timer ticks = 0.5us at this board's 170MHz TIM1 clock. */
#define FOC_PWM_COMMON_MODE_RESERVE_TICKS 85U

/* Pure planning. Three equal integer offsets preserve the pairwise CCR
 * differences of the ORIGINAL 5..95%-bounded/quantized duty command exactly.
 * No per-phase clipping after translation, no voltage-vector scaling, no
 * register writes, no dynamic memory. Unsupported geometry fails closed.
 * Only negative/common downward translation is used at the fixed near-peak
 * trigger; infeasible commands are rejected, never replaced by held PWM here. */
FocWindowStatus FocPwmCommonMode_Plan(const FocWindowConfig *cfg,
    float u,float v,float w,uint16_t trigger,uint16_t reserve,
    FocWindowPlan *plan,int16_t *offset);

typedef struct {
    uint32_t plans,adjusted,rejected;
    int32_t last_offset;
    uint32_t max_abs_offset,min_slack_ticks;
} FocPwmCommonModeDiag;
#endif
