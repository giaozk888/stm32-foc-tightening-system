#ifndef MECHANICAL_DOB_SHADOW_H
#define MECHANICAL_DOB_SHADOW_H
#include <math.h>
#include <stdint.h>
/* Current-normalized mechanical model. Kt is NOT needed for A-equivalent
 * disturbance estimation. Nothing in this interface can write an actuator,
 * PI, current reference, protection threshold or persistent parameter. */
typedef struct {
    /* Ic and bias must be separated by a qualified bidirectional model.
     * A positive-only intercept (Ic+bias) is NOT a calibrated Coulomb term. */
    float j_over_kt,b_over_kt,coulomb_over_kt,bias_a;
    float bandwidth_rad_s,min_speed_rad_s;
    uint32_t qualified;
} MechanicalNormalizedModel;
typedef struct {
    float omega_lpf,drive_lpf,disturbance_a,elapsed_s;
    uint32_t initialized,valid,status;
} MechanicalDobShadow;
enum { DOB_SHADOW_UNCONFIGURED=1U,DOB_SHADOW_BAD_SAMPLE=2U,DOB_SHADOW_ZERO_SPEED=4U,
       DOB_SHADOW_WARMUP=8U,DOB_SHADOW_FAULT=16U };
static inline void MechanicalDob_Reset(MechanicalDobShadow *s,uint32_t status)
{
    *s=(MechanicalDobShadow){.status=status};
#if defined(FOC_DOB_ID_TRACE)
    /* Diagnostic-only event hook AFTER the original reset. No state setter. */
    extern void DobIdTrace_ResetEvent(uint32_t reason);
    DobIdTrace_ResetEvent(status);
#endif
}
static inline void MechanicalDob_Observe(MechanicalDobShadow *s,
    const MechanicalNormalizedModel *m,float iq,float omega,float dt,
    uint8_t sample_valid,uint8_t protection_fault)
{
    if (protection_fault) {MechanicalDob_Reset(s,DOB_SHADOW_FAULT);return;}
    if (!m->qualified || !isfinite(m->j_over_kt) || m->j_over_kt<=0 ||
        !isfinite(m->b_over_kt) || m->b_over_kt<0 ||
        !isfinite(m->coulomb_over_kt) || m->coulomb_over_kt<0 || !isfinite(m->bias_a) ||
        !isfinite(m->bandwidth_rad_s) || m->bandwidth_rad_s<=0 || m->bandwidth_rad_s>125.66371f ||
        !isfinite(m->min_speed_rad_s) || m->min_speed_rad_s<=0) {
        MechanicalDob_Reset(s,DOB_SHADOW_UNCONFIGURED);return;
    }
    if (!sample_valid || !isfinite(iq) || !isfinite(omega) || !isfinite(dt) || dt<.0001f || dt>.010f) {
        MechanicalDob_Reset(s,DOB_SHADOW_BAD_SAMPLE);return;
    }
    if (fabsf(omega)<m->min_speed_rad_s) {MechanicalDob_Reset(s,DOB_SHADOW_ZERO_SPEED);return;}
    float drive=iq-m->b_over_kt*omega-m->coulomb_over_kt*(omega>0?1.f:-1.f)-m->bias_a;
    if (!isfinite(drive)) {MechanicalDob_Reset(s,DOB_SHADOW_BAD_SAMPLE);return;}
    if (!s->initialized) {
        s->omega_lpf=omega;s->drive_lpf=drive;s->initialized=1U;
        s->status=DOB_SHADOW_WARMUP;s->valid=0;s->elapsed_s=0;s->disturbance_a=0;return;
    }
    float g=m->bandwidth_rad_s,k=dt*g/(1.f+dt*g);
    s->omega_lpf+=k*(omega-s->omega_lpf);s->drive_lpf+=k*(drive-s->drive_lpf);
    /* Q(s)[Iq - B/Kt*w - Tc/Kt*sign(w) - bias] - J/Kt*s*Q(s)*w.
     * Same pole for drive and derivative, no raw finite-difference amplifier. */
    float estimate=s->drive_lpf-m->j_over_kt*g*(omega-s->omega_lpf);
    if (!isfinite(estimate)) {MechanicalDob_Reset(s,DOB_SHADOW_BAD_SAMPLE);return;}
    s->elapsed_s+=dt;s->disturbance_a=estimate;
    s->valid=(uint32_t)(s->elapsed_s*g>=5.f);
    s->status=s->valid?0U:DOB_SHADOW_WARMUP;
    /* OBSERVE ONLY. No return value intended for an Iq summing junction. */
}
#endif
