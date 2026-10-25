#include "ka_sync_diagnostic.h"
#include <math.h>
#include <limits.h>
_Static_assert(sizeof(KaSyncPoint)==18U,"Sync point ABI");
_Static_assert(sizeof(KaSyncDiagnostic)==1212U,"Sync buffer ABI");
_Static_assert(sizeof(KaSyncCurrent)==20U,"Sync current ABI");
void KaSync_Reset(KaSyncDiagnostic *s)
{
    ++s->generation;s->count=0;s->active=0;s->observations=0;s->read_failures=0;s->flags=0;
    s->net_iq_lpf=0;
    /* Do not clear the IRQ-owned current publication or allocate a ring temporary. */
}
static int16_t quantize(float value,float scale,uint8_t *flags)
{
    float x=value*scale;
    if (!isfinite(x) || x>32767 || x< -32768) { *flags|=KAS_RANGE;return 0; }
    return (int16_t)(x>=0 ? x+.5f : x-.5f);
}
void KaSync_Observe(KaSyncDiagnostic *s,uint32_t now,uint32_t enc,uint32_t dt,
    uint16_t raw,int32_t delta,float speed,float friction,uint8_t saturated,
    const KaSyncCurrent *current,uint8_t valid)
{
    if (s->count>=KA_SYNC_CAPACITY) return;
    if (!s->active) { s->active=1;s->begin_us=enc; }
    ++s->observations;
    /* Diagnostic copies only: same variable-dt LPF as control speed, but NEVER
     * fed back into either PI. Preserve states before the short window. */
    float net_before=s->net_iq_lpf;
    if (valid && dt>0 && dt<=2000U && isfinite(current->iq) && isfinite(friction)) {
        float seconds=(float)dt*.000001f;
        float alpha=seconds/(.020f+seconds);
        s->net_iq_lpf+=alpha*((current->iq-friction)-s->net_iq_lpf);
    }
    if ((uint32_t)(enc-s->begin_us)<KA_SYNC_START_US) return;
    uint8_t flags=0;KaSyncPoint p={0};
    uint32_t age=now-enc;
    if (!dt || dt>2000U) flags|=KAS_GAP;
    if (age>2000U) flags|=KAS_ENCODER_AGE;
    if (dt>65535U || age>65535U || delta<INT16_MIN || delta>INT16_MAX) flags|=KAS_RANGE;
    p.encoder_dt_us=(uint16_t)dt;p.task_age_us=(uint16_t)age;p.raw_delta=(int16_t)delta;
    if (!valid) { flags|=KAS_NO_CURRENT;++s->read_failures; }
    uint32_t seq=valid?current->source_seq:s->last_adc_seq;
    int32_t relative=valid?(int32_t)(current->source_us-enc):0;
    if (relative<INT16_MIN || relative>INT16_MAX) flags|=KAS_RANGE;
    p.current_relative_us=(int16_t)relative;
    if (valid && ((uint32_t)(now-current->source_us)>200U ||
                  (uint32_t)(current->published_us-current->source_us)>100U)) flags|=KAS_CURRENT_AGE;
    if (!s->count) {
        s->first_encoder_us=enc;s->first_adc_seq=seq;
        s->first_raw_before=(uint16_t)((raw-delta)&16383);
        s->first_net_iq_lpf_before=net_before;
    } else {
        uint32_t step=seq-s->last_adc_seq;
        if (!step || step>255U || enc-s->last_encoder_us!=dt) flags|=KAS_SEQUENCE;
        p.adc_seq_step=(uint8_t)step;
    }
    p.iq_0p1ma=quantize(valid?current->iq:0,10000,&flags);
    p.speed_0p01rpm=quantize(speed,100,&flags);
    p.friction_0p1ma=quantize(friction,10000,&flags);
    p.iq_minus_friction_lpf_0p1ma=quantize(s->net_iq_lpf,10000,&flags);
    if (saturated) flags|=KAS_SATURATED;
    p.flags=flags;s->flags|=flags;
    s->last_encoder_us=enc;s->last_adc_seq=seq;
    s->points[s->count]=p;KaSync_Barrier();++s->count;
}
