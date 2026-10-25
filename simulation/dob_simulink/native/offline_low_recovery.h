#ifndef DOB_OFFLINE_LOW_RECOVERY_H
#define DOB_OFFLINE_LOW_RECOVERY_H
/* SOFTWARE EXPERIMENT ONLY. Not included by either MCU application.
 * Run the original monitor on every actual epoch; only retain observer state
 * through a bounded low-speed hole. No source epoch is reconstructed. */
#include "mechanical_dob_monitor.h"
#define OLR_LOW_US 100000U
#ifndef OLR_RETURN_US
#define OLR_RETURN_US 150000U
#endif
#define OLR_QUIET_US 20000U
#define OLR_W_RANGE .5f
#define OLR_DRIVE_RANGE .010f
#define OLR_CONFIRM_STATUS 4096U
enum { OLR_NORMAL,OLR_LOW,OLR_RETURN,OLR_REBASED,OLR_COLD };
enum { OLR_NONE,OLR_LONG,OLR_SOURCE,OLR_REVERSE,OLR_RETURN_TIMEOUT,OLR_FAULT };
typedef struct {
    MechanicalDobShadow held;
    uint32_t mode,reason,low_start,return_start,quiet_start,quiet_n;
    uint32_t fast,cold,held_epochs,confirm_epochs,low_max_us;
    float sign,quiet_w0,w_min,w_max,drive_min,drive_max,drive_sum;
} OfflineLowRecovery;
static inline void Olr_Cold(OfflineLowRecovery *g,MechanicalDobMonitor *m,uint32_t why){
    if(g->mode!=OLR_COLD)++g->cold;
    /* The original cold observer runs in parallel. A failed fast attempt
     * must not restart its already-earned warmup and make recovery slower. */
    if(g->mode==OLR_REBASED){MechanicalDob_Reset(&m->observer,DOB_SHADOW_WARMUP);m->current.valid=0;m->current.status|=DOB_SHADOW_WARMUP;}
    g->mode=OLR_COLD;g->reason=why;g->quiet_n=0;g->held=(MechanicalDobShadow){0};
}
static inline void Olr_Hold(OfflineLowRecovery *g,MechanicalDobMonitor *m,uint32_t status){
    (void)g;
    m->current.valid=0;m->current.disturbance_a=0;
    m->current.status=(m->current.status&DOB_MONITOR_SATURATED)|status;
}
static inline void OfflineLow_Observe(OfflineLowRecovery *g,MechanicalDobMonitor *m,
    uint32_t now,uint32_t enc,uint32_t dt,float omega,uint8_t saturated,
    const MechanicalCurrent *c,uint8_t valid,uint8_t enabled){
    const MechanicalNormalizedModel *model=&mechanical_dob_identified_model;
    int low=isfinite(omega)&&fabsf(omega)<model->min_speed_rad_s;
    if(enabled&&g->mode==OLR_NORMAL&&low&&m->running&&!m->frozen&&
       m->observer.valid&&m->current.valid&&dob_current_admission.armed){
        g->held=m->observer;g->sign=m->current.omega_rad_s>0?1.f:-1.f;
        g->low_start=enc;g->quiet_n=0;g->mode=OLR_LOW;g->reason=OLR_NONE;
    }
    MechanicalDobMonitor_Observe(m,now,enc,dt,omega,saturated,c,valid);
    if(!enabled)return;
    if(!m->running||m->frozen){
        if(g->mode==OLR_LOW||g->mode==OLR_RETURN||g->mode==OLR_REBASED){
            ++g->cold;g->mode=OLR_COLD;g->reason=OLR_FAULT;g->quiet_n=0;g->held=(MechanicalDobShadow){0};
        }
        return;
    }
    if(g->mode==OLR_COLD){if(m->current.valid){g->mode=OLR_NORMAL;g->reason=OLR_NONE;}return;}
    if(g->mode==OLR_NORMAL)return;
    uint32_t allowed=DOB_SHADOW_ZERO_SPEED|DOB_SHADOW_WARMUP|DOB_MONITOR_SATURATED;
    if(!valid||!isfinite(omega)||m->current.status&~allowed||!dob_current_admission.filter_updated){
        Olr_Cold(g,m,OLR_SOURCE);return;
    }
    if(omega*g->sign<0){Olr_Cold(g,m,OLR_REVERSE);return;}
    if(g->mode==OLR_LOW){
        uint32_t length=enc-g->low_start;if(length>g->low_max_us)g->low_max_us=length;
        if(length>OLR_LOW_US){Olr_Cold(g,m,OLR_LONG);return;}
        if(low){++g->held_epochs;Olr_Hold(g,m,DOB_SHADOW_ZERO_SPEED);return;}
        g->return_start=enc;g->quiet_n=0;g->mode=OLR_RETURN;
    }else if(low){Olr_Cold(g,m,OLR_REVERSE);return;}
    if(g->mode==OLR_REBASED){
        if(m->current.status&DOB_MONITOR_SATURATED){Olr_Cold(g,m,OLR_SOURCE);return;}
        if(m->current.valid){g->mode=OLR_NORMAL;++g->fast;}
        return;
    }
    if(m->current.valid){Olr_Cold(g,m,OLR_RETURN_TIMEOUT);return;}
    if(enc-g->return_start>OLR_RETURN_US){Olr_Cold(g,m,OLR_RETURN_TIMEOUT);return;}
    ++g->confirm_epochs;
    float drive=m->iq_lpf-model->b_over_kt*omega-model->coulomb_over_kt*g->sign-model->bias_a;
    if(fabsf(omega)<DOB_FRESH_FEEDBACK_MIN_RAD_S||(m->current.status&DOB_MONITOR_SATURATED)||!isfinite(drive))g->quiet_n=0;
    else{
        if(!g->quiet_n){
            g->quiet_start=enc;g->quiet_w0=omega;g->w_min=g->w_max=omega;
            g->drive_min=g->drive_max=drive;g->drive_sum=0;
        }
        g->w_min=fminf(g->w_min,omega);g->w_max=fmaxf(g->w_max,omega);
        g->drive_min=fminf(g->drive_min,drive);g->drive_max=fmaxf(g->drive_max,drive);
        g->drive_sum+=drive;++g->quiet_n;
        if(g->w_max-g->w_min>OLR_W_RANGE||g->drive_max-g->drive_min>OLR_DRIVE_RANGE)g->quiet_n=0;
        else if(enc-g->quiet_start>=OLR_QUIET_US){
            /* A real quiet window estimates drive minus measured endpoint
             * inertia. Bumpless state projection; retained elapsed contains
             * only past real updates, never time spent in the hole. */
            float span=(float)(enc-g->quiet_start)*1e-6f;
            float estimate=g->drive_sum/(float)g->quiet_n-model->j_over_kt*(omega-g->quiet_w0)/span;
            g->held.omega_lpf=omega;g->held.drive_lpf=estimate;g->held.disturbance_a=estimate;
            m->observer=g->held;m->observer.valid=0;m->observer.status=OLR_CONFIRM_STATUS;
            g->mode=OLR_REBASED;
        }
    }
    Olr_Hold(g,m,OLR_CONFIRM_STATUS);
}
#endif
