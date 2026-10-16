/* Frozen pre-optimization interval search. Test oracle only, never linked to
 * firmware. Keep independent of the specialized two-interval implementation. */
#include "foc_adc_window.h"
#include <stddef.h>
#include <string.h>

FocWindowStatus FocAdcWindow_Reference(const FocWindowConfig *cfg,
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
    uint16_t edge[3] = {phase[0], phase[1], phase[2]};
    for (unsigned i = 0; i < 3U; ++i) {
        if (phase[i] == 0U || phase[i] >= cfg->arr)
            return FOC_WINDOW_BAD_ARGUMENT;
        for (unsigned j = i; j > 0U && edge[j] < edge[j - 1U]; --j) {
            uint16_t tmp = edge[j]; edge[j] = edge[j - 1U]; edge[j - 1U] = tmp;
        }
    }
    const int32_t period = 2 * (int32_t)cfg->arr;
    const int32_t guard = (int32_t)cfg->dead_ticks + cfg->settle_ticks;
    const int32_t tail = (int32_t)cfg->latency_ticks + cfg->aperture_ticks;
    const int32_t uv_max = phase[0] > phase[1] ? phase[0] : phase[1];
    int32_t best_width = -1, best_trigger = -1;
    int32_t left = -(int32_t)edge[0];
    for (unsigned segment = 0; segment < 4U; ++segment) {
        int32_t right = segment < 3U ? edge[segment] : period - edge[2];
        int32_t lo = left + guard;
        int32_t hi = right - guard - tail;
        if (cfg->topology == FOC_SENSE_LOW_SIDE_UV) {
            int32_t uv_lo = uv_max + guard;
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
