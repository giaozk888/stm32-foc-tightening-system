#include "mechanical_identification.h"
#include <math.h>
#include <limits.h>
_Static_assert(sizeof(MechanicalPoint)==36U,"Mechanical point ABI");
_Static_assert(sizeof(MechanicalCapture)==4712U,"Mechanical capture RAM budget");
_Static_assert(sizeof(MechanicalCurrent)==28U,"Mechanical publication ABI");
void Mechanical_Reset(MechanicalCapture *s)
{
    ++s->generation;s->count=0;s->observations=0;s->flags=0;s->read_failures=0;s->active=0;
    /* No ring memset, IRQ-owned timing maximum is not reset. */
}
void Mechanical_Observe(MechanicalCapture *s,uint32_t now,uint32_t enc,uint32_t dt,
    int32_t delta,float omega,uint8_t iq_sat,const MechanicalCurrent *c,uint8_t valid)
{
    if (s->count>=MECH_CAPTURE_CAPACITY) return; /* frozen, never wraps */
    ++s->observations;
    uint32_t flags=0;
    if (!valid) {flags|=MEC_NO_CURRENT;++s->read_failures;}
    if (!dt || dt>2000U) flags|=MEC_TIME;
    if (now-enc>2000U) flags|=MEC_ENCODER;
    if (valid && (now-c->source_us>200U || c->published_us-c->source_us>100U)) flags|=MEC_AGE;
    if (!isfinite(omega) || (valid && (!isfinite(c->id) || !isfinite(c->iq)))) flags|=MEC_RANGE;
    if (valid) flags|=c->flags;
    if (iq_sat) flags|=MEC_SATURATED;
    if (delta>8192 || delta< -8192) {flags|=MEC_RANGE;delta=0;}
    if (!s->active) {
        s->active=1U;s->first_encoder_us=enc;s->last_encoder_us=enc;
        s->first_seq=valid?c->seq:0;s->last_seq=s->first_seq;s->last_adc_seq=s->first_seq;
        s->first_omega=isfinite(omega)?omega:0;s->prev_omega=s->first_omega;
        s->iq_lpf=valid && isfinite(c->iq)?c->iq:0;s->prev_iq=s->iq_lpf;
        s->bin_start_us=enc;s->last_observe_us=enc;s->bin_samples=0;s->bin_flags=flags;
        s->raw_sum=0;s->duration_s=0;s->iq_integral=0;s->matched_integral=0;
        s->id_abs_integral=0;s->omega_integral=0;s->flags|=flags;return;
    }
    if (enc-s->last_observe_us!=dt || (valid &&
        (!((uint32_t)(c->seq-s->last_adc_seq)) || (uint32_t)(c->seq-s->last_adc_seq)>80U)))
        flags|=MEC_SEQUENCE;
    if (valid && !(flags&(MEC_TIME|MEC_RANGE|MEC_NO_CURRENT))) {
        float seconds=(float)dt*1e-6f,previous=s->iq_lpf;
        /* Diagnostic-only matched 20ms pole; NEVER supplied to a controller. */
        s->iq_lpf+=seconds/(.020f+seconds)*(c->iq-s->iq_lpf);
        s->iq_integral+=.5f*(s->prev_iq+c->iq)*seconds;
        s->matched_integral+=.5f*(previous+s->iq_lpf)*seconds;
        s->id_abs_integral+=fabsf(c->id)*seconds;
        s->omega_integral+=.5f*(s->prev_omega+omega)*seconds;
        s->duration_s+=seconds;s->prev_iq=c->iq;s->prev_omega=omega;
    }
    s->last_observe_us=enc;
    if (valid) s->last_adc_seq=c->seq;
    if ((delta>0 && s->raw_sum>INT32_MAX-delta) ||
        (delta<0 && s->raw_sum<INT32_MIN-delta)) flags|=MEC_RANGE;
    else s->raw_sum+=delta;
    ++s->bin_samples;s->bin_flags|=flags;s->flags|=flags;
    uint32_t interval=enc-s->bin_start_us;
    if (interval<MECH_CAPTURE_BIN_US) return;
    flags=s->bin_flags;
    if (interval>65535U || s->bin_samples>65535U || s->raw_sum<INT16_MIN ||
        s->raw_sum>INT16_MAX || s->duration_s<=0) flags|=MEC_RANGE;
    float duration=s->duration_s>0?s->duration_s:1.f;
    MechanicalPoint p={.end_us=enc,.adc_seq=s->last_adc_seq,.dt_us=(uint16_t)interval,
        .samples=(uint16_t)s->bin_samples,.mechanical_raw_delta=(int16_t)s->raw_sum,
        .flags=(uint16_t)flags,.omega_end_rad_s=isfinite(omega)?omega:0,
        .omega_mean_rad_s=s->omega_integral/duration,.iq_mean_a=s->iq_integral/duration,
        .iq_matched_mean_a=s->matched_integral/duration,.id_abs_mean_a=s->id_abs_integral/duration};
    s->points[s->count]=p;KaSync_Barrier();++s->count;
    s->flags|=flags;s->last_encoder_us=enc;s->last_seq=s->last_adc_seq;
    s->bin_start_us=enc;s->bin_samples=0;s->bin_flags=0;s->raw_sum=0;
    s->duration_s=0;s->iq_integral=0;s->matched_integral=0;s->id_abs_integral=0;s->omega_integral=0;
}
