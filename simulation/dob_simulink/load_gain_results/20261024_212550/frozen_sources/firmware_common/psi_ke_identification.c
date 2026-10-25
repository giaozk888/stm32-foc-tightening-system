#include "psi_ke_identification.h"
#include <math.h>

int PsiIdent_Allowed(int32_t rpm,float api_limit,float trip_limit)
{
    return (rpm==100 || rpm==200 || rpm==300 || rpm==400) &&
        (float)rpm<=api_limit && (float)rpm<trip_limit;
}
uint8_t PsiIdent_Calculate(PsiIdentFrame *f,float rs,float ld,uint32_t pairs)
{
    f->quality=PSI_Q_VALID;f->rpm=0.0f;
    f->resistive=f->cross=f->bemf=f->psi=0.0f;
    if (!pairs || !isfinite(rs) || rs<=0 || !isfinite(ld) || ld<=0 ||
        !isfinite(f->we) || !isfinite(f->id) || !isfinite(f->iq) ||
        !isfinite(f->vd) || !isfinite(f->vq)) { f->quality=PSI_Q_BAD_INPUT;return 0U; }
    /* Existing signed encoder electrical speed is the coherent source. Its
     * inverse reports the mechanical rpm represented by THAT same frame. */
    f->rpm=f->we/((float)pairs*0.1047197551196598f);
    if (fabsf(f->rpm)<PSI_MIN_VALID_RPM) { f->quality=PSI_Q_LOW_SPEED;return 0U; }
    f->resistive=rs*f->iq;
    f->cross=f->we*ld*f->id;
    f->bemf=f->vq-f->resistive-f->cross;
    f->psi=f->bemf/f->we;
    if (!isfinite(f->psi) || !isfinite(f->bemf)) { f->quality=PSI_Q_BAD_INPUT;return 0U; }
    return 1U;
}
void PsiIdent_Finish(PsiIdentification *s,uint8_t no_fault)
{
    s->finished=1U;
    s->passed=(uint8_t)(no_fault && s->window_start && s->window_complete &&
        s->valid>=PSI_MIN_VALID_SAMPLES && s->seen &&
        (float)s->reject<=PSI_MAX_REJECT_FRACTION*(float)s->seen);
    s->stage=!no_fault ? PSI_ABORT : s->passed ? PSI_DONE : PSI_QUALITY;
}
void PsiIdent_Observe(PsiIdentification *s,PsiIdentFrame f,float reference,float accel,
    uint8_t healthy,uint32_t observation_us)
{
    if (!s->active || s->finished) return;
    uint8_t fresh=(uint8_t)(f.seq!=s->last_seq);s->last_seq=f.seq;
    f.index=s->latest.index+1U;
    if (!healthy || f.saturated || f.fault) f.quality=PSI_Q_UNHEALTHY;
    else if (!fresh) f.quality=PSI_Q_DUPLICATE;
    else if (!isfinite(reference) || !isfinite(accel) ||
        fabsf(reference-(float)s->rpm)>.001f || fabsf(accel)>.001f)
        f.quality=PSI_Q_MOVING_REFERENCE;
    else if (fabsf(f.rpm-(float)s->rpm)>
        fmaxf(PSI_SPEED_TOL_MIN_RPM,PSI_SPEED_TOL_FRACTION*fabsf((float)s->rpm)))
        f.quality=PSI_Q_SPEED;
    if (!s->window_start) {
        if (f.quality) s->stable_since=0U;
        else {
            if (!s->stable_since) s->stable_since=observation_us;
            if ((uint32_t)(observation_us-s->stable_since)>=PSI_STABLE_US) {
                s->window_start=observation_us;s->stage=PSI_COLLECT;
            }
        }
    }
    if (s->window_start) {
        ++s->seen;
        if (f.quality) ++s->reject;
        else {
            const float v[8]={f.rpm,f.id,f.iq,f.vq,f.bemf,f.psi,f.we,f.vd};
            ++s->valid;
            float old=s->mean[5];
            for (unsigned k=0;k<8U;++k) s->mean[k]+=(v[k]-s->mean[k])/(float)s->valid;
            s->psi_m2+=(f.psi-old)*(f.psi-s->mean[5]);
        }
        if ((uint32_t)(observation_us-s->window_start)>=PSI_WINDOW_US) {
            s->window_complete=1U;PsiIdent_Finish(s,1U);
        }
    }
    f.stage=s->stage;s->latest=f;
}
