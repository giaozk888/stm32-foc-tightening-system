#ifndef FOC_PWM_WRITE_PROBE_H
#define FOC_PWM_WRITE_PROBE_H
#include <stdint.h>
#include <limits.h>

/* RCR=0 center-aligned: UEV at BOTH endpoints, irrespective of CMS CC-IRQ
 * selection. The application's checked commit specifically targets bottom.
 * Never infer success from the next modulo bottom after a missed deadline. */
typedef struct { uint32_t dwt, count, span; uint8_t down, valid; } FocPwmPoint;
typedef struct {
    uint32_t points, invalid, late_update_count, writes, possible_suppressed_uev_count;
    int32_t pwm_update_margin_ticks_min;
    uint32_t next_uev_ticks_min, ccr_write_cycles_max;
    FocPwmPoint entry, write_begin, write_end, worst; /* entry/worst are one worst-margin pair. */
    uint32_t geometry[8]; /* CR1 CR2 ARR PSC RCR CCMR1 CCMR2 ADC1_JSQR */
} FocPwmWriteProbe;

static inline uint32_t FocPwm_Bottom(uint32_t arr,FocPwmPoint p)
{ return p.down ? p.count : 2U*arr-p.count; }
static inline uint32_t FocPwm_NextUev(uint32_t arr,FocPwmPoint p)
{ return p.down ? p.count : arr-p.count; }
#if defined(FOC_PREEMPT_COMMIT_PROBE)
/* One shared diagnostic reducer; keep it out of both call-site expansions. */
static __attribute__((noinline,unused,optimize("Os"))) void
#else
static inline void
#endif
FocPwm_Observe(FocPwmWriteProbe *s,uint32_t arr,
    FocPwmPoint entry,FocPwmPoint point,uint8_t actual_write,
    FocPwmPoint begin,uint32_t guard)
{
    if (actual_write) ++s->writes; /* Count writes even if their evidence is invalid. */
    uint32_t elapsed=point.dwt-entry.dwt;
    if (!entry.valid || !point.valid || entry.count>arr || point.count>arr ||
        !arr || arr>32767U || elapsed>INT32_MAX ||
        (actual_write && (!begin.valid || begin.count>arr))) { ++s->invalid; return; }
    int32_t margin=(int32_t)FocPwm_Bottom(arr,entry)-(int32_t)elapsed;
    uint32_t next=FocPwm_NextUev(arr,point);
    next=next>point.span ? next-point.span : 0U;
    if (!s->points || margin<s->pwm_update_margin_ticks_min) {
        s->pwm_update_margin_ticks_min=margin; s->entry=entry; s->worst=point;
    }
    if (!s->points || next<s->next_uev_ticks_min) s->next_uev_ticks_min=next;
    ++s->points;
    if (margin<=(int32_t)guard) ++s->late_update_count;
    if (actual_write) {
        uint32_t duration=point.dwt-begin.dwt;
        if (duration>s->ccr_write_cycles_max) s->ccr_write_cycles_max=duration;
        /* Legacy transaction timestamps enclose UDIS. In the non-invasive
         * pipeline they enclose plain stores: this legacy-named field then
         * denotes a POSSIBLE mixed-latch crossing, NOT UEV suppression.
         * Neither interpretation directly observes an internal latch. */
        if (duration>=FocPwm_NextUev(arr,begin)) ++s->possible_suppressed_uev_count;
        s->write_begin=begin; s->write_end=point;
    }
}
#endif
