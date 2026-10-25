#ifndef MECHANICAL_IDENTIFICATION_H
#define MECHANICAL_IDENTIFICATION_H
#include "ka_sync_diagnostic.h" /* bounded versioned publication / barriers only */
#define MECH_CAPTURE_CAPACITY 128U
#define MECH_CAPTURE_BIN_US 64000U
enum { MEC_NO_CURRENT=1U,MEC_TIME=2U,MEC_AGE=4U,MEC_SEQUENCE=8U,
       MEC_RANGE=16U,MEC_SATURATED=32U,MEC_ENCODER=64U };
typedef struct {
    uint32_t version,seq,source_us,published_us;
    float id,iq;
    uint32_t flags;
} MechanicalCurrent;
typedef struct {
    uint32_t end_us,adc_seq;
    uint16_t dt_us,samples;
    int16_t mechanical_raw_delta;
    uint16_t flags;
    float omega_end_rad_s,omega_mean_rad_s;
    float iq_mean_a,iq_matched_mean_a,id_abs_mean_a;
} MechanicalPoint;
typedef struct {
    MechanicalPoint points[MECH_CAPTURE_CAPACITY];
    uint32_t generation,count,observations,flags,first_encoder_us,last_encoder_us;
    uint32_t first_seq,last_seq,read_failures,publish_cycles_max;
    float first_omega;
    uint32_t active,bin_start_us,last_observe_us,last_adc_seq,bin_samples,bin_flags;
    int32_t raw_sum;
    float duration_s,iq_lpf,prev_iq,iq_integral,matched_integral;
    float id_abs_integral,omega_integral,prev_omega;
} MechanicalCapture;
static inline void Mechanical_Publish(volatile MechanicalCurrent *s,uint32_t seq,
    uint32_t source,uint32_t now,float id,float iq,uint32_t flags)
{
    ++s->version;KaSync_Barrier();
    s->seq=seq;s->source_us=source;s->published_us=now;s->id=id;s->iq=iq;s->flags=flags;
    KaSync_Barrier();++s->version;
}
static inline uint8_t Mechanical_TryRead(const volatile MechanicalCurrent *s,MechanicalCurrent *out)
{
    for (unsigned i=0;i<2U;++i) {
        uint32_t before=s->version;
        if (!before || (before&1U)) continue;
        KaSync_Barrier();
        MechanicalCurrent c={before,s->seq,s->source_us,s->published_us,s->id,s->iq,s->flags};
        KaSync_Barrier();
        if (before==s->version) {*out=c;return 1U;}
    }
    return 0U; /* no IRQ mask, no unbounded spin */
}
void Mechanical_Reset(MechanicalCapture *s);
void Mechanical_Observe(MechanicalCapture *s,uint32_t now,uint32_t encoder_us,
    uint32_t dt_us,int32_t mechanical_raw_delta,float omega_rad_s,uint8_t iq_saturated,
    const MechanicalCurrent *current,uint8_t valid);
#endif
