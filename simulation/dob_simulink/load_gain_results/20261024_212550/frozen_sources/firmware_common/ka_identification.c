#include "ka_identification.h"
#include <math.h>
#include <stddef.h>
_Static_assert(sizeof(KaIdentFrame)==40U,"Ka observation ABI");
_Static_assert(offsetof(KaIdentification,generation)==960U,"Ka ring ABI");
_Static_assert(sizeof(KaIdentification)==1032U,"Ka observer RAM budget");
void KaIdent_Reset(KaIdentification *s)
{
    /* Invalidate old frames without a 1 KB memset/stack temporary. */
    ++s->generation;s->count=0;s->samples=0;s->started=0;
}
void KaIdent_Observe(KaIdentification *s,const SpeedAccelFfFrame *f,float friction,
    uint32_t now,uint32_t encoder_us,uint32_t adc_count)
{
    if (s->count>=KA_IDENT_CAPACITY) return;
    uint32_t flags=0;
    if (!f->valid || !isfinite(f->speed_meas_rpm) || !isfinite(f->iq_meas_a) ||
        !isfinite(f->speed_ref_rpm) || !isfinite(friction)) flags|=KAI_BAD_INPUT;
    if (f->saturated) flags|=KAI_SATURATED;
    if ((uint32_t)(now-encoder_us)>2000U) flags|=KAI_ENCODER_STALE;
    if (s->started) {
        uint32_t dt_us=now-s->last_us;
        if (!dt_us || dt_us>KA_IDENT_MAX_GAP_US || f->seq!=s->last_seq+1U) flags|=KAI_SAMPLE_GAP;
        if (adc_count==s->last_adc_count) flags|=KAI_CURRENT_STALE;
        s->flags|=flags;
        /* Never poison a binary window with NaN. Flagged windows are kept,
         * not used for identification; this does NOT reject a control sample. */
        if (!(flags&KAI_BAD_INPUT) && dt_us<=KA_IDENT_MAX_GAP_US) {
            float dt=(float)dt_us*0.000001f;
            s->iq_integral+=0.5f*(s->last_iq+f->iq_meas_a)*dt;
            s->friction_integral+=0.5f*(s->last_friction+friction)*dt;
            s->ref_integral+=0.5f*(s->last_ref+f->speed_ref_rpm)*dt;
            s->speed_integral+=0.5f*(s->last_speed+f->speed_meas_rpm)*dt;
        }
        if ((uint32_t)(now-s->start_us)>=KA_IDENT_WINDOW_US) {
            float duration=(float)(now-s->start_us)*0.000001f;
            s->frames[s->count]=(KaIdentFrame){s->count+1U,s->start_us,now,s->flags,
                s->start_speed,f->speed_meas_rpm,s->iq_integral/duration,
                s->friction_integral/duration,s->ref_integral/duration,s->speed_integral/duration};
            ++s->count; /* MonitorTask copies under its existing task critical section. */
            s->started=0;
        }
    }
    if (!s->started) {
        s->start_us=now;s->start_speed=f->speed_meas_rpm;s->flags=flags;
        s->iq_integral=0;s->friction_integral=0;s->ref_integral=0;s->speed_integral=0;
        s->started=1;
    }
    ++s->samples;s->last_us=now;s->last_seq=f->seq;s->last_adc_count=adc_count;
    s->last_speed=f->speed_meas_rpm;s->last_iq=f->iq_meas_a;
    s->last_friction=friction;s->last_ref=f->speed_ref_rpm;
}
