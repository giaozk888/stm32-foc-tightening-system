#include "foc_adc_window.h"
#include "foc_hot_path.h"
#include <math.h>
#include <stddef.h>
#include <string.h>

FOC_RAM_PATH FocWindowStatus FocAdcWindow_Plan(const FocWindowConfig *cfg,
                                const uint16_t phase[3], FocWindowPlan *out)
{
    if (out != NULL) memset(out, 0, sizeof(*out));
    if (cfg == NULL || phase == NULL || out == NULL || cfg->arr < 4U ||
        cfg->arr > 32767U || cfg->aperture_ticks == 0U)
        return FOC_WINDOW_BAD_ARGUMENT;
    if (cfg->topology == FOC_SENSE_UNCONFIRMED)
        return FOC_WINDOW_TOPOLOGY_UNKNOWN;
    if (cfg->topology != FOC_SENSE_INLINE && cfg->topology != FOC_SENSE_LOW_SIDE_UV)
        return FOC_WINDOW_BAD_ARGUMENT;
    if ((cfg->placement != FOC_SAMPLE_WINDOW_MIDPOINT &&
         cfg->placement != FOC_SAMPLE_LATE_BEFORE_PEAK) ||
        (cfg->min_low_on_ticks != 0U && cfg->topology != FOC_SENSE_LOW_SIDE_UV))
        return FOC_WINDOW_BAD_ARGUMENT;
    for (unsigned i = 0; i < 3U; ++i)
        if (phase[i] == 0U || phase[i] >= cfg->arr)
            return FOC_WINDOW_BAD_ARGUMENT;
    const int32_t period = 2 * (int32_t)cfg->arr;
    const int32_t guard = (int32_t)cfg->dead_ticks + cfg->settle_ticks;
    const int32_t tail = (int32_t)cfg->latency_ticks + cfg->aperture_ticks;
    const int32_t uv_max = phase[0] > phase[1] ? phase[0] : phase[1];
    if (cfg->topology == FOC_SENSE_LOW_SIDE_UV &&
        cfg->placement == FOC_SAMPLE_LATE_BEFORE_PEAK) {
        /* U/V must both have turned on, so their earlier intervals cannot
         * contain a valid sample. Only W can split the remaining interval.
         * Try the peak-side interval first: if valid it is globally latest.
         * Otherwise try before W. No sort or four-segment search is needed.
         * Preserve ALL original guards, aperture and RC recovery constraints. */
        int32_t uv_lo = uv_max + guard;
        const int32_t rc_lo = uv_max + cfg->dead_ticks + cfg->min_low_on_ticks;
        if (uv_lo < rc_lo) uv_lo = rc_lo;
        if (uv_lo < 1) uv_lo = 1;
        int32_t hi = (int32_t)cfg->arr - 1 - tail;
        const int32_t max_edge = phase[2] > uv_max ? phase[2] : uv_max;
        const int32_t peak_hi = period - max_edge - guard - tail;
        if (hi > peak_hi) hi = peak_hi;
        int32_t lo = max_edge + guard;
        if (lo < uv_lo) lo = uv_lo;
        if (hi < lo && phase[2] > uv_max) {
            /* W's downward edge is farther away than its upward edge here. */
            hi = (int32_t)phase[2] - guard - tail;
            const int32_t before_peak = (int32_t)cfg->arr - 1 - tail;
            if (hi > before_peak) hi = before_peak;
            lo = uv_lo;
        }
        if (hi < lo) return FOC_WINDOW_TOO_SHORT;
        memcpy(out->phase, phase, sizeof(out->phase));
        out->earliest = (uint16_t)lo;
        out->latest = out->trigger = (uint16_t)hi;
        out->slack_ticks = (uint16_t)(hi - lo);
        return FOC_WINDOW_OK;
    }
    uint16_t edge[3] = {phase[0], phase[1], phase[2]};
    for (unsigned i = 0; i < 3U; ++i) {
        for (unsigned j = i; j > 0U && edge[j] < edge[j - 1U]; --j) {
            uint16_t tmp = edge[j]; edge[j] = edge[j - 1U]; edge[j - 1U] = tmp;
        }
    }
    int32_t best_width = -1;
    int32_t best_trigger = -1;
    /* First interval includes the stable bottom across the previous period;
     * last interval includes the stable peak across the downward count. */
    int32_t left = -(int32_t)edge[0];
    for (unsigned segment = 0; segment < 4U; ++segment) {
        int32_t right = segment < 3U ? edge[segment] : period - edge[2];
        int32_t lo = left + guard;
        int32_t hi = right - guard - tail;
        if (cfg->topology == FOC_SENSE_LOW_SIDE_UV) {
            int32_t uv_lo = uv_max + guard;
            /* RC recovery is measured from low-side turn-on, not from the
             * beginning of the timer period. Do not unnecessarily impose
             * the full RC budget on W, which only needs edge blanking. */
            int32_t rc_lo = uv_max + cfg->dead_ticks + cfg->min_low_on_ticks;
            if (uv_lo < rc_lo) uv_lo = rc_lo;
            int32_t uv_hi = period - uv_max - guard - tail;
            if (lo < uv_lo) lo = uv_lo;
            if (hi > uv_hi) hi = uv_hi;
        }
        if (lo < 1) lo = 1;
        if (hi > (int32_t)cfg->arr - 1) hi = (int32_t)cfg->arr - 1;
        if (cfg->placement == FOC_SAMPLE_LATE_BEFORE_PEAK &&
            hi > (int32_t)cfg->arr - 1 - tail)
            hi = (int32_t)cfg->arr - 1 - tail;
        int32_t candidate = cfg->placement == FOC_SAMPLE_LATE_BEFORE_PEAK ?
                            hi : lo + (hi - lo) / 2;
        int better = cfg->placement == FOC_SAMPLE_LATE_BEFORE_PEAK ?
                     candidate >= best_trigger : hi - lo >= best_width;
        if (hi >= lo && better) {
            best_width = hi - lo;
            best_trigger = candidate;
            out->earliest = (uint16_t)lo;
            out->latest = (uint16_t)hi;
            out->trigger = (uint16_t)candidate;
            out->slack_ticks = (uint16_t)(hi - lo);
        }
        left = right;
    }
    if (best_width < 0) return FOC_WINDOW_TOO_SHORT;
    memcpy(out->phase, phase, sizeof(out->phase));
    return FOC_WINDOW_OK;
}

FOC_RAM_PATH FocWindowStatus FocAdcWindow_Duty(const FocWindowConfig *cfg,
                                float u, float v, float w, FocWindowPlan *out)
{
    if (cfg == NULL || out == NULL || cfg->arr < 4U || cfg->arr > 32767U ||
        !isfinite(u) || !isfinite(v) || !isfinite(w)) {
        if (out != NULL) memset(out, 0, sizeof(*out));
        return FOC_WINDOW_BAD_ARGUMENT;
    }
    float duty[3] = {u, v, w};
    uint16_t phase[3];
    for (unsigned i = 0; i < 3U; ++i) {
        if (duty[i] < 0.05f) duty[i] = 0.05f;
        if (duty[i] > 0.95f) duty[i] = 0.95f;
        phase[i] = (uint16_t)(duty[i] * (float)(cfg->arr + 1U));
    }
    return FocAdcWindow_Plan(cfg, phase, out);
}

void FocRawSpread_Reset(FocRawSpread *s)
{
    memset(s, 0, sizeof(*s));
}
void FocRawSpread_Push(FocRawSpread *s, uint16_t u, uint16_t v)
{
    if (s->count >= FOC_SPREAD_BLOCK || u > 4095U || v > 4095U) return;
    const uint16_t raw[2] = {u, v};
    for (unsigned i = 0; i < 2U; ++i) {
        uint16_t x = raw[i];
        if (s->count == 0U) s->min[i] = s->max[i] = x;
        if (x < s->min[i]) s->min[i] = x;
        if (x > s->max[i]) s->max[i] = x;
        if (s->count != 0U) {
            uint16_t delta = x > s->previous[i] ? x - s->previous[i] : s->previous[i] - x;
            if (delta > s->max_step[i]) s->max_step[i] = delta;
        }
        s->previous[i] = x;
        s->sum[i] += x;
        s->sum_sq[i] += (uint32_t)x * x; /* 4095^2 * 256 fits uint32_t */
    }
    ++s->count;
}
