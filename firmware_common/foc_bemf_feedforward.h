#ifndef FOC_BEMF_FEEDFORWARD_H
#define FOC_BEMF_FEEDFORWARD_H
#include <math.h>
#include <stdint.h>

#ifndef FOC_BEMF_ENABLED_DEFAULT
#define FOC_BEMF_ENABLED_DEFAULT 0
#endif
#ifndef FOC_BEMF_PSI_WB
#define FOC_BEMF_PSI_WB 0.0f
#endif

/* Phase-peak PM flux linkage (Wb = V/(electrical rad/s)), NOT line-line
 * RMS Ke or rpm/V Kv. Zero means UNCALIBRATED, not a guessed motor value.
 * Existing Park: q=-alpha*sin(theta)+beta*cos(theta), hence +omega_e*psi.
 * Use the existing SIGNED measured electrical rad/s, never speed command.
 * No inductive dq cross terms, Rs compensation, observer or new filter. */
static inline uint8_t FocBemf_Configured(void)
{
    return (uint8_t)(isfinite(FOC_BEMF_PSI_WB) && FOC_BEMF_PSI_WB>0.0f);
}
static inline uint8_t FocBemf_Apply(uint8_t enabled,float omega_e,float *vq_ff)
{
    *vq_ff=0.0f;
    if (!enabled) return 1U; /* OFF ignores inputs, exact original PI path. */
    if (!FocBemf_Configured() || !isfinite(omega_e)) return 0U;
    float q=omega_e*FOC_BEMF_PSI_WB;
    if (!isfinite(q)) return 0U;
    *vq_ff=q;
    return 1U;
}

#if defined(FOC_BEMF_GAIN_DIAG)
/* Diagnostic only: explicit idle command selects one of five reduced fluxes.
 * Zero is a true OFF path. Never extrapolate beyond the existing flux. */
static inline uint8_t FocBemfGain_Valid(uint32_t percent)
{
    return (uint8_t)(percent==0U || percent==25U || percent==50U ||
                     percent==75U || percent==100U);
}
static inline uint8_t FocBemfGain_Apply(uint8_t enabled,float omega_e,
                                      uint32_t percent,float *vq_ff)
{
    *vq_ff=0.0f;
    if (!enabled) return 1U;
    if (!FocBemfGain_Valid(percent)) return 0U;
    if (!percent) return 1U;
    if (!FocBemf_Apply(1U,omega_e,vq_ff)) return 0U;
    *vq_ff *= (float)percent*0.01f;
    return (uint8_t)isfinite(*vq_ff);
}
#endif

/* Latest coherent accepted-PI frame, not a high-rate historical recorder.
 * Single ISR writer; task copies under a short mask, formats after unmask. */
typedef struct {
    uint32_t seq,source_us,enabled,saturated,valid;
    float omega_e,id,iq,vd_pi,vq_pi,vq_ff,vd,vq;
} FocBemfFrame;
#endif
