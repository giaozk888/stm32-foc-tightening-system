#include "foc_pwm_common_mode.h"
#include "foc_hot_path.h"
#include <math.h>
#include <string.h>

FOC_RAM_PATH __attribute__((optimize("Os")))
FocWindowStatus FocPwmCommonMode_Plan(const FocWindowConfig *c,
    float u,float v,float w,uint16_t trigger,uint16_t reserve,
    FocWindowPlan *out,int16_t *offset)
{
    if (out) memset(out,0,sizeof(*out));
    if (offset) *offset=0;
    if (!c || !out || !offset || c->arr<4U || c->arr>32767U ||
        c->topology!=FOC_SENSE_LOW_SIDE_UV ||
        c->placement!=FOC_SAMPLE_LATE_BEFORE_PEAK ||
        !c->aperture_ticks || !trigger || trigger>=c->arr ||
        !isfinite(u) || !isfinite(v) || !isfinite(w)) return FOC_WINDOW_BAD_ARGUMENT;
    const int32_t tail=(int32_t)c->latency_ticks+c->aperture_ticks;
    if ((int32_t)trigger+tail>=c->arr) return FOC_WINDOW_TOO_SHORT;
    const int32_t guard=(int32_t)c->dead_ticks+c->settle_ticks;
    int32_t edge_cap=(int32_t)trigger-guard-reserve;
    int32_t reverse_cap=2*(int32_t)c->arr-trigger-tail-guard-reserve;
    if (edge_cap>reverse_cap) edge_cap=reverse_cap;
    int32_t uv_cap=(int32_t)trigger-c->dead_ticks-c->min_low_on_ticks-reserve;
    if (uv_cap>edge_cap) uv_cap=edge_cap;
    /* Identical pre-quantization bounds to FocAdcWindow_Duty. Preserve these
     * quantized differences, not an already clipped unbounded input vector. */
    const uint16_t floor_ccr=(uint16_t)(0.05f*(float)(c->arr+1U));
    float duty[3]={u,v,w}; uint16_t phase[3]; int32_t shift=0;
    for (unsigned i=0;i<3U;++i) {
        if (duty[i]<0.05f) duty[i]=0.05f;
        if (duty[i]>0.95f) duty[i]=0.95f;
        phase[i]=(uint16_t)(duty[i]*(float)(c->arr+1U));
        int32_t cap=i<2U ? uv_cap : edge_cap;
        int32_t allowed=cap-phase[i];
        if (shift>allowed) shift=allowed;
    }
    for (unsigned i=0;i<3U;++i) {
        int32_t translated=(int32_t)phase[i]+shift;
        if (translated<floor_ccr || translated<=0 || translated>=c->arr)
            return FOC_WINDOW_TOO_SHORT;
        phase[i]=(uint16_t)translated;
    }
    /* The unchanged authoritative planner must accept the complete result.
     * Never move CCR4 to rescue a command or trust only our quick bounds. */
    FocWindowStatus status=FocAdcWindow_Plan(c,phase,out);
    if (status==FOC_WINDOW_OK && out->trigger==trigger && out->slack_ticks>=reserve) {
        *offset=(int16_t)shift;
        return FOC_WINDOW_OK;
    }
    memset(out,0,sizeof(*out));
    return status==FOC_WINDOW_OK ? FOC_WINDOW_TOO_SHORT : status;
}
