#ifndef PSI_KE_IDENTIFICATION_H
#define PSI_KE_IDENTIFICATION_H
#include <stdint.h>
#define PSI_MIN_VALID_RPM 50.0f
#define PSI_STABLE_US 500000U
#define PSI_WINDOW_US 2000000U
#define PSI_OBSERVE_US 50000U
#define PSI_MAX_FRAME_AGE_US 100U /* Estimator admission only, no guard change. */
#define PSI_DRIVE_MS 5000U
#define PSI_STOP_MS 7000U
#define PSI_MIN_VALID_SAMPLES 38U
#define PSI_MAX_REJECT_FRACTION 0.05f
#define PSI_SPEED_TOL_FRACTION 0.05f
#define PSI_SPEED_TOL_MIN_RPM 2.0f
enum { PSI_WAIT=0,PSI_COLLECT=1,PSI_DONE=2,PSI_QUALITY=3,PSI_ABORT=4 };
enum { PSI_Q_VALID=0,PSI_Q_LOW_SPEED=1,PSI_Q_BAD_INPUT=2,PSI_Q_UNHEALTHY=3,
       PSI_Q_MOVING_REFERENCE=4,PSI_Q_SPEED=5,PSI_Q_DUPLICATE=6 };
typedef struct {
    uint32_t index,seq,us,quality,saturated,fault,stage;
    float rpm,we,id,iq,vd,vq,resistive,cross,bemf,psi;
} PsiIdentFrame;
typedef struct {
    PsiIdentFrame latest;
    /* means: rpm,Id,Iq,Vq,bemf,psi,we,Vd; Welford variance only for psi. */
    float mean[8],psi_m2,start_angle,net_travel;
    uint32_t encoder_before,start_us,stable_since,window_start,last_observe,last_seq;
    uint32_t seen,valid,reject,stop_good_ms,stage;
    int32_t rpm;
    uint8_t used,queued,prepared,admitting,active,finished,passed,window_complete;
} PsiIdentification;
#ifdef __cplusplus
extern "C" {
#endif
int PsiIdent_Allowed(int32_t rpm,float api_limit,float trip_limit);
void PsiIdent_Observe(PsiIdentification *s,PsiIdentFrame f,float reference,float accel,
    uint8_t healthy,uint32_t observation_us);
void PsiIdent_Finish(PsiIdentification *s,uint8_t no_fault);
uint8_t PsiIdent_Calculate(PsiIdentFrame *f,float rs,float ld,uint32_t pairs);
void PsiIdent_Log(const PsiIdentFrame *f);
#ifdef __cplusplus
}
#endif
#endif
