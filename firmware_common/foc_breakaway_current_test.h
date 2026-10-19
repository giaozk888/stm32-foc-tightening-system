#ifndef FOC_BREAKAWAY_CURRENT_TEST_H
#define FOC_BREAKAWAY_CURRENT_TEST_H
#include <stdint.h>
#include <string.h>

/* Diagnostic-only constants, NOT production PI or protection thresholds.
 * mA commands, one request per boot. A host may orchestrate separate sessions. */
#define BREAKAWAY_CURRENT_MAX_MA             250U
#if defined(FOC_BREAKAWAY_FIVE_SECOND)
#define BREAKAWAY_TEST_DURATION_US       5000000U
#define BREAKAWAY_RECORD_PERIOD_US        200000U
#define BREAKAWAY_CAPTURE_TAG          0x42574135U
#else
#define BREAKAWAY_TEST_DURATION_US        200000U
#define BREAKAWAY_RECORD_PERIOD_US          8000U
#define BREAKAWAY_CAPTURE_TAG          0x42574159U
#endif

/* Host-only provisional motion classification, shared through literal macros.
 * Decimated software encoder evidence cannot certify physical torque. */
#define BREAKAWAY_MIN_FRAMES                  20U
#define BREAKAWAY_MIN_COVERAGE_US         180000U
#define BREAKAWAY_MAX_RECORD_GAP_US        16000U
#define BREAKAWAY_MAX_FIRST_RECORD_US      20000U
#define BREAKAWAY_MAX_END_RECORD_US       250000U
#define BREAKAWAY_MIN_NET_TRAVEL_DEG         3.0f
#define BREAKAWAY_NO_MOTION_TRAVEL_DEG       0.25f
#define BREAKAWAY_MAX_PATH_TO_NET_RATIO      1.20f
#define BREAKAWAY_MIN_FORWARD_FRACTION       0.80f
#define BREAKAWAY_MIN_MOVING_FRACTION        0.70f
#define BREAKAWAY_MAX_STATIONARY_US         40000U
#define BREAKAWAY_MIN_TAIL_TRAVEL_DEG        0.50f
#define BREAKAWAY_IQ_MEAN_ERROR_RATIO        0.25f
#define BREAKAWAY_IQ_MAE_RATIO               0.30f
#define BREAKAWAY_IQ_ERROR_FLOOR_A           0.03f
#define BREAKAWAY_MAX_WRONG_IQ_FRACTION      0.10f
#define BREAKAWAY_MIN_ACCEPTED_FRACTION      0.95f
#define BREAKAWAY_MIN_CONFIRMED_REPEATS         3U
#define BREAKAWAY_ASYMMETRY_RATIO            0.20f
#define BREAKAWAY_FF_MARGIN_RATIO            0.15f

#if defined(FOC_BREAKAWAY_FIVE_SECOND)
/* Task-only, all fresh outer observations, not just the 32 saved frames.
 * Raw encoder distance prevents the 200ms trace decimation from hiding
 * sub-frame back-and-forth motion. Integer counters, no ISR work. */
typedef struct {
    uint32_t count, first_us, last_us, max_gap_us;
    int32_t net_counts, positive_counts, negative_counts;
    uint32_t absolute_counts, forward, backward, stationary;
    uint32_t stationary_start_us, max_stationary_us;
    uint32_t tail_absolute_counts;
    int32_t tail_net_counts;
    uint32_t bad_ref, bad_gates, bad_encoder;
    uint16_t last_raw, reserved;
} FocBreakawayMotion;
__attribute__((optimize("Os"),unused))
static void FocBreakaway_Observe(FocBreakawayMotion *s,uint32_t us,
    uint16_t raw,int32_t sign,uint8_t ref_ok,uint8_t gates_ok,uint8_t encoder_ok)
{
    ++s->bad_ref; s->bad_ref-=!!ref_ok;
    ++s->bad_gates; s->bad_gates-=!!gates_ok;
    ++s->bad_encoder; s->bad_encoder-=!!encoder_ok;
    if (s->count) {
        uint32_t dt=us-s->last_us;
        if (dt>s->max_gap_us) s->max_gap_us=dt;
        int32_t d=(int32_t)raw-s->last_raw;
        if (d>8192) d-=16384;
        if (d< -8192) d+=16384;
        d=-d; /* Existing encoder direction -1; no control sign changes. */
        uint32_t a=(uint32_t)(d<0 ? -d : d);
        s->net_counts+=d; s->absolute_counts+=a;
        if (s->net_counts>s->positive_counts) s->positive_counts=s->net_counts;
        if (s->net_counts<s->negative_counts) s->negative_counts=s->net_counts;
        if (us>=3333333U) { s->tail_net_counts+=d; s->tail_absolute_counts+=a; }
        if (d*sign>0) ++s->forward;
        else if (d*sign<0) ++s->backward;
        else ++s->stationary;
        if (d) s->stationary_start_us=us;
        uint32_t held=us-s->stationary_start_us;
        if (held>s->max_stationary_us) s->max_stationary_us=held;
    } else s->first_us=s->stationary_start_us=us;
    s->last_raw=raw; s->last_us=us; ++s->count;
}
#endif

static inline int FocBreakaway_Candidate(uint16_t ma)
{
    return ma==100U || ma==120U || ma==150U || ma==180U || ma==200U || ma==250U;
}
static inline int FocBreakaway_WithinLimit(uint16_t ma,uint16_t direct_limit_ma)
{
    return FocBreakaway_Candidate(ma) && ma<=BREAKAWAY_CURRENT_MAX_MA && ma<=direct_limit_ma;
}
static inline int FocBreakaway_Parse(const char *cmd,int32_t *sign,uint16_t *ma)
{
    const char *prefix="MOTOR TEST BREAKAWAY ";
    if (strncmp(cmd,prefix,21U)) return 0;
    cmd+=21U;
    if (!strncmp(cmd,"POS ",4U)) *sign=1;
    else if (!strncmp(cmd,"NEG ",4U)) *sign=-1;
    else return 0;
    cmd+=4U;
    if (strlen(cmd)!=11U || strcmp(cmd+3U," CONFIRM")) return 0;
    if (cmd[0]<'0' || cmd[0]>'9' || cmd[1]<'0' || cmd[1]>'9' || cmd[2]<'0' || cmd[2]>'9') return 0;
    *ma=(uint16_t)((cmd[0]-'0')*100+(cmd[1]-'0')*10+cmd[2]-'0');
    return FocBreakaway_Candidate(*ma);
}
#endif
