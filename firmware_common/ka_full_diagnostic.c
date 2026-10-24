#include "ka_full_diagnostic.h"
#include <math.h>
#include <limits.h>
_Static_assert(sizeof(KaFullPoint)==24U,"Full point ABI");
_Static_assert(sizeof(KaFullDiagnostic)==5872U,"Full buffer ABI");
void KaFull_Reset(KaFullDiagnostic *s)
{
    ++s->generation;s->count=0;s->observations=0;s->active=0;s->flags=0;
    s->read_failures=0;s->net_lpf=0;
    /* IRQ-owned publish_cycles_max is deliberately not reset. No array memset. */
}
static int16_t quantize(float v,float scale,uint8_t *flags)
{
    float x=v*scale;
    if (!isfinite(x) || x>32767 || x< -32768) { *flags|=KAS_RANGE;return 0; }
    return (int16_t)(x>=0?x+.5f:x-.5f);
}
void KaFull_Observe(KaFullDiagnostic *s,uint32_t now,uint32_t enc,uint32_t dt,
    uint16_t raw,int32_t delta,float speed,float ref,float accel,float fric,
    uint8_t saturated,const KaSyncCurrent *c,uint8_t valid)
{
    if (s->count>=KA_FULL_CAPACITY) return;
    ++s->observations;
    uint8_t flags=0;
    if (!valid) { flags|=KAS_NO_CURRENT;++s->read_failures; }
    if (!dt || dt>2000U) flags|=KAS_GAP;
    if (now-enc>2000U) flags|=KAS_ENCODER_AGE;
    if (valid && ((uint32_t)(now-c->source_us)>200U ||
                  (uint32_t)(c->published_us-c->source_us)>100U)) flags|=KAS_CURRENT_AGE;
    if (!isfinite(speed) || !isfinite(ref) || !isfinite(accel) || !isfinite(fric) ||
        (valid && !isfinite(c->iq))) flags|=KAS_RANGE;
    if (saturated) flags|=KAS_SATURATED;
    if (!s->active) {
        s->active=1;s->begin_us=enc;s->first_encoder_us=enc;s->last_encoder_us=enc;
        s->first_adc_seq=valid?c->source_seq:0;s->last_adc_seq=s->first_adc_seq;
        s->first_speed=speed;s->first_ref=ref;s->first_raw=raw;s->reserved=0;
        s->bin_start_us=enc;s->bin_seq=s->first_adc_seq;s->last_observe_us=enc;
        s->last_observe_seq=s->first_adc_seq;s->interval_samples=0;s->interval_flags=flags;
        s->duration_s=0;s->iq_integral=0;s->friction_integral=0;s->net_integral=0;s->raw_sum=0;
        s->prev_iq=valid?c->iq:0;s->flags|=flags;return;
    }
    if (enc-s->last_observe_us!=dt || (valid &&
        (!((uint32_t)(c->source_seq-s->last_observe_seq)) ||
         (uint32_t)(c->source_seq-s->last_observe_seq)>80U))) flags|=KAS_SEQUENCE;
    if (valid && !(flags&(KAS_NO_CURRENT|KAS_GAP|KAS_RANGE))) {
        float seconds=(float)dt*.000001f,previous=s->net_lpf;
        s->net_lpf+=seconds/(.020f+seconds)*((c->iq-fric)-s->net_lpf);
        s->iq_integral+=.5f*(s->prev_iq+c->iq)*seconds;
        s->friction_integral+=fric*seconds;
        s->net_integral+=.5f*(previous+s->net_lpf)*seconds;
        s->duration_s+=seconds;s->prev_iq=c->iq;
    }
    s->last_observe_us=enc;s->last_observe_seq=valid?c->source_seq:s->last_observe_seq;
    s->raw_sum+=delta;++s->interval_samples;s->interval_flags|=flags;s->flags|=flags;
    uint32_t interval=enc-s->bin_start_us;
    if (interval<KA_FULL_BIN_US) return;
    KaFullPoint p={0};flags=(uint8_t)s->interval_flags;
    int32_t relative=valid?(int32_t)(c->source_us-enc):0;
    uint32_t seq=valid?c->source_seq:s->last_adc_seq,step=seq-s->bin_seq,age=now-enc;
    if (interval>65535U || age>65535U || step>65535U || !step ||
        relative<INT16_MIN || relative>INT16_MAX || s->raw_sum<INT16_MIN ||
        s->raw_sum>INT16_MAX || s->interval_samples>255U || s->duration_s<=0) flags|=KAS_RANGE;
    p.interval_us=(uint16_t)interval;p.task_age_us=(uint16_t)age;
    p.current_relative_us=(int16_t)relative;p.adc_seq_step=(uint16_t)step;
    p.raw_delta=(int16_t)s->raw_sum;p.samples=(uint8_t)s->interval_samples;
    float duration=s->duration_s>0?s->duration_s:1;
    p.iq_mean_0p1ma=quantize(s->iq_integral/duration,10000,&flags);
    p.friction_mean_0p1ma=quantize(s->friction_integral/duration,10000,&flags);
    p.net_lpf_mean_0p1ma=quantize(s->net_integral/duration,10000,&flags);
    p.speed_0p01rpm=quantize(speed,100,&flags);p.reference_0p01rpm=quantize(ref,100,&flags);
    p.accel_ref_0p1rpm_s=quantize(accel,10,&flags);p.flags=flags;s->flags|=flags;
    s->last_encoder_us=enc;s->last_adc_seq=seq;s->points[s->count]=p;
    KaSync_Barrier();++s->count;
    s->bin_start_us=enc;s->bin_seq=seq;s->interval_samples=0;s->interval_flags=0;
    s->duration_s=0;s->iq_integral=0;s->friction_integral=0;s->net_integral=0;s->raw_sum=0;
}
