#ifndef FOC_OVERCURRENT_SHADOW_H
#define FOC_OVERCURRENT_SHADOW_H
#include <stdint.h>

/* Diagnostic-only observer. No decision from this module may gate PWM,
 * suppress the independent raw trip, or clear a fault. Units are PHYSICAL
 * sample pairs, not delayed/replaced feedback pairs. Fixed three-phase work.
 * A "single" means one hit followed by TWO observed healthy samples; a
 * stopped stream must remain pending, never be called a harmless spike.
 * NOISE is provisional: >=3 resolved singles in a rolling 32-sample window.
 * This is a diagnostic classification, not a validated protection setting. */
typedef struct {
    uint32_t hits, singles, single_window;
    uint8_t pending, misses;
} FocOcShadowPhase;
typedef struct {
    FocOcShadowPhase phase[3];
    uint32_t samples, last_seq, gaps, invalid;
    uint8_t seq_valid, confirmed_mask, noise_mask, last_mask;
} FocOcShadow;

static inline uint32_t FocOcShadow_Inc(uint32_t v)
{ return v == UINT32_MAX ? v : v + 1U; }
static inline void FocOcShadow_Begin(FocOcShadow *s)
{ *s = (FocOcShadow){0}; }
static inline uint8_t FocOcShadow_Pending(const FocOcShadow *s)
{
    return s->phase[0].pending | (uint8_t)(s->phase[1].pending << 1U) |
           (uint8_t)(s->phase[2].pending << 2U);
}
static inline void FocOcShadow_BreakContinuity(FocOcShadow *s)
{
    for (unsigned i=0; i<3U; ++i) {
        s->phase[i].pending=0U; s->phase[i].misses=0U;
        s->phase[i].single_window=0U;
    }
}
static inline void FocOcShadow_Push(FocOcShadow *s, uint32_t seq,
                                  uint8_t mask, uint8_t valid)
{
    s->samples=FocOcShadow_Inc(s->samples);
    if (s->seq_valid && (uint32_t)(seq-s->last_seq)!=1U) {
        s->gaps=FocOcShadow_Inc(s->gaps);
        FocOcShadow_BreakContinuity(s); /* Never bridge missing samples. */
    }
    s->last_seq=seq; s->seq_valid=1U;
    if (!valid || (mask & ~7U)) {
        s->invalid=FocOcShadow_Inc(s->invalid);
        FocOcShadow_BreakContinuity(s); s->last_mask=0U; return;
    }
    s->last_mask=mask;
    for (unsigned i=0; i<3U; ++i) {
        FocOcShadowPhase *p=&s->phase[i]; uint8_t bit=(uint8_t)(1U<<i);
        p->single_window <<= 1U;
        if (mask & bit) p->hits=FocOcShadow_Inc(p->hits);
        if (s->confirmed_mask & bit) continue; /* Sticky until explicit begin. */
        if (mask & bit) {
            if (p->pending) {
                s->confirmed_mask |= bit; p->pending=0U; p->misses=0U;
            } else { p->pending=1U; p->misses=0U; }
        } else if (p->pending && ++p->misses>=2U) {
            p->pending=0U; p->misses=0U;
            p->singles=FocOcShadow_Inc(p->singles); p->single_window |= 1U;
            uint32_t bits=p->single_window;
            bits &= bits-1U; bits &= bits-1U;
            if (bits) s->noise_mask |= bit;
        }
    }
}
/* Same signed U/V and reconstructed-W interpretation as the existing trip.
 * Compute masks separately for physical and filtered pairs; do not join them. */
static inline uint8_t FocOcShadow_Mask(float u, float v, float w, float limit)
{
    return (uint8_t)((u>limit || u< -limit) |
        ((v>limit || v< -limit)<<1U) | ((w>limit || w< -limit)<<2U));
}
#endif
