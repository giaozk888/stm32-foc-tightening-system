#ifndef KA_SYNC_DIAGNOSTIC_H
#define KA_SYNC_DIAGNOSTIC_H
#include <stdint.h>
#define KA_SYNC_CAPACITY 64U
#ifndef KA_SYNC_START_US
#define KA_SYNC_START_US 600000U
#endif
enum { KAS_NO_CURRENT=1U,KAS_GAP=2U,KAS_RANGE=4U,KAS_CURRENT_AGE=8U,
       KAS_SEQUENCE=16U,KAS_ENCODER_AGE=32U,KAS_SATURATED=64U };
/* Diagnostic publication only. Single ADC writer; task reader never masks IRQs. */
typedef struct {
    uint32_t version,source_seq,source_us,published_us;
    float iq;
} KaSyncCurrent;
typedef struct {
    uint16_t encoder_dt_us,task_age_us;
    int16_t current_relative_us;
    uint8_t adc_seq_step,flags;
    int16_t raw_delta,iq_0p1ma,speed_0p01rpm,friction_0p1ma;
    int16_t iq_minus_friction_lpf_0p1ma;
} KaSyncPoint;
typedef struct {
    KaSyncPoint points[KA_SYNC_CAPACITY];
    uint32_t generation,count,begin_us,first_encoder_us,first_adc_seq;
    uint32_t last_encoder_us,last_adc_seq,observations,read_failures,flags,active;
    uint32_t publish_cycles_max;
    uint16_t first_raw_before,reserved;
    float net_iq_lpf,first_net_iq_lpf_before;
} KaSyncDiagnostic;
static inline void KaSync_Barrier(void)
{
#if defined(__arm__) || defined(__thumb__)
    __asm__ volatile("dmb" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}
static inline void KaSync_Publish(volatile KaSyncCurrent *s,uint32_t seq,
    uint32_t source_us,uint32_t published_us,float iq)
{
    ++s->version;KaSync_Barrier();
    s->source_seq=seq;s->source_us=source_us;s->published_us=published_us;s->iq=iq;
    KaSync_Barrier();++s->version;
}
static inline uint8_t KaSync_TryRead(const volatile KaSyncCurrent *s,KaSyncCurrent *out)
{
    for (unsigned i=0;i<2;++i) {
        uint32_t before=s->version;if (!before || (before&1U)) continue;
        KaSync_Barrier();
        KaSyncCurrent copy={before,s->source_seq,s->source_us,s->published_us,s->iq};
        KaSync_Barrier();
        if (before==s->version) { *out=copy;return 1; }
    }
    return 0;
}
#ifdef __cplusplus
extern "C" {
#endif
void KaSync_Reset(KaSyncDiagnostic *s);
void KaSync_Observe(KaSyncDiagnostic *s,uint32_t now,uint32_t encoder_us,uint32_t encoder_dt_us,
    uint16_t raw,int32_t raw_delta,float speed_filtered,float friction,uint8_t saturated,
    const KaSyncCurrent *current,uint8_t current_valid);
#ifdef __cplusplus
}
#endif
#endif
