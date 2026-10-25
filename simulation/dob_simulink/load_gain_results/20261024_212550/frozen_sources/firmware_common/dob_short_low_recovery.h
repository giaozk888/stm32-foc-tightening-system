#ifndef DOB_SHORT_LOW_RECOVERY_H
#define DOB_SHORT_LOW_RECOVERY_H
/* Candidate A only. Hooks run inside the monitor writer seqlock.
 * Original cold path continues in parallel. No reconstructed source epochs. */
#include "mechanical_dob_monitor.h"
#if defined(FOC_DOB_LOW_AUDIT)
#include "dob_low_recovery_audit.h"
#define DLR_RECORD(why,site) DobLowAudit_Record(g,m,enc,omega,valid,why,site)
#else
#define DLR_RECORD(why,site) ((void)0)
#endif
#define DLR_LOW_US 100000U
#ifndef DLR_RETURN_US
#define DLR_RETURN_US 200000U
#endif
#define DLR_QUIET_US 20000U
#define DLR_W_RANGE .5f
#define DLR_DRIVE_RANGE .010f
#define DLR_CONFIRM_STATUS 4096U
enum { DLR_NORMAL,DLR_LOW,DLR_RETURN,DLR_REBASED,DLR_COLD };
enum { DLR_NONE,DLR_LONG,DLR_SOURCE,DLR_REVERSE,DLR_RETURN_TIMEOUT,DLR_FAULT };
typedef struct {
    MechanicalDobShadow held;
    uint32_t mode,reason,low_start,return_start,quiet_start,quiet_n;
    uint32_t fast,cold,held_epochs,confirm_epochs,low_max_us;
    float sign,quiet_w0,w_min,w_max,drive_min,drive_max,drive_sum;
} DobLowRecovery;
static inline void Dlr_Cold(DobLowRecovery *g,MechanicalDobMonitor *m,uint32_t why){
    if(g->mode!=DLR_COLD)++g->cold;
    /* The original cold observer runs in parallel. A failed fast attempt
     * must not restart its already-earned warmup and make recovery slower. */
    if(g->mode==DLR_REBASED){MechanicalDob_Reset(&m->observer,DOB_SHADOW_WARMUP);m->current.valid=0;m->current.status|=DOB_SHADOW_WARMUP;}
    g->mode=DLR_COLD;g->reason=why;g->quiet_n=0;g->held=(MechanicalDobShadow){0};
}
static inline void Dlr_Hold(DobLowRecovery *g,MechanicalDobMonitor *m,uint32_t status){
    (void)g;
    m->current.valid=0;m->current.disturbance_a=0;
    m->current.status=(m->current.status&DOB_MONITOR_SATURATED)|status;
}
extern DobLowRecovery dob_low_recovery;
_Static_assert(sizeof(DobLowRecovery)==100U,"Short-low candidate bounded RAM");
static inline void Dlr_Before(DobLowRecovery *g,MechanicalDobMonitor *m,uint32_t enc,float omega){
    const MechanicalNormalizedModel *model=&mechanical_dob_identified_model;
    int low=isfinite(omega)&&fabsf(omega)<model->min_speed_rad_s;
    if(g->mode==DLR_NORMAL&&low&&m->running&&!m->frozen&&
       m->observer.valid&&m->current.valid&&dob_current_admission.armed){
        g->held=m->observer;g->sign=m->current.omega_rad_s>0?1.f:-1.f;
        g->low_start=enc;g->quiet_n=0;g->mode=DLR_LOW;g->reason=DLR_NONE;
    }
}
static inline void Dlr_After(DobLowRecovery *g,MechanicalDobMonitor *m,uint32_t enc,float omega,uint8_t valid){
    const MechanicalNormalizedModel *model=&mechanical_dob_identified_model;
    if(!m->running||m->frozen){
        if(g->mode==DLR_LOW||g->mode==DLR_RETURN||g->mode==DLR_REBASED){
            DLR_RECORD(DLR_FAULT,DLR_LOG_LIFECYCLE);
            ++g->cold;g->mode=DLR_COLD;g->reason=DLR_FAULT;g->quiet_n=0;g->held=(MechanicalDobShadow){0};
        }
        return;
    }
    if(g->mode==DLR_COLD){if(m->current.valid){g->mode=DLR_NORMAL;g->reason=DLR_NONE;}return;}
    if(g->mode==DLR_NORMAL)return;
    uint32_t allowed=DOB_SHADOW_ZERO_SPEED|DOB_SHADOW_WARMUP|DOB_MONITOR_SATURATED;
    if(!valid||!isfinite(omega)||m->current.status&~allowed||!dob_current_admission.filter_updated){
        DLR_RECORD(DLR_SOURCE,DLR_LOG_SOURCE);
        Dlr_Cold(g,m,DLR_SOURCE);return;
    }
    int low=isfinite(omega)&&fabsf(omega)<model->min_speed_rad_s;
    if(omega*g->sign<0){DLR_RECORD(DLR_REVERSE,DLR_LOG_DIRECTION);Dlr_Cold(g,m,DLR_REVERSE);return;}
    if(g->mode==DLR_LOW){
        uint32_t length=enc-g->low_start;if(length>g->low_max_us)g->low_max_us=length;
        if(length>DLR_LOW_US){DLR_RECORD(DLR_LONG,DLR_LOG_LONG);Dlr_Cold(g,m,DLR_LONG);return;}
        if(low){++g->held_epochs;Dlr_Hold(g,m,DOB_SHADOW_ZERO_SPEED);return;}
        g->return_start=enc;g->quiet_n=0;g->mode=DLR_RETURN;
    }else if(low){DLR_RECORD(DLR_REVERSE,DLR_LOG_RELOW);Dlr_Cold(g,m,DLR_REVERSE);return;}
    if(g->mode==DLR_REBASED){
        if(m->current.status&DOB_MONITOR_SATURATED){DLR_RECORD(DLR_SOURCE,DLR_LOG_REBASED_SAT);Dlr_Cold(g,m,DLR_SOURCE);return;}
        if(m->current.valid){g->mode=DLR_NORMAL;++g->fast;}
        return;
    }
    if(m->current.valid){DLR_RECORD(DLR_RETURN_TIMEOUT,DLR_LOG_COLD_READY);Dlr_Cold(g,m,DLR_RETURN_TIMEOUT);return;}
    if(enc-g->return_start>DLR_RETURN_US){DLR_RECORD(DLR_RETURN_TIMEOUT,DLR_LOG_TIMEOUT);Dlr_Cold(g,m,DLR_RETURN_TIMEOUT);return;}
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
        if(g->w_max-g->w_min>DLR_W_RANGE||g->drive_max-g->drive_min>DLR_DRIVE_RANGE)g->quiet_n=0;
        else if(enc-g->quiet_start>=DLR_QUIET_US){
            /* A real quiet window estimates drive minus measured endpoint
             * inertia. Bumpless state projection; retained elapsed contains
             * only past real updates, never time spent in the hole. */
            float span=(float)(enc-g->quiet_start)*1e-6f;
            float estimate=g->drive_sum/(float)g->quiet_n-model->j_over_kt*(omega-g->quiet_w0)/span;
            g->held.omega_lpf=omega;g->held.drive_lpf=estimate;g->held.disturbance_a=estimate;
            m->observer=g->held;m->observer.valid=0;m->observer.status=DLR_CONFIRM_STATUS;
            g->mode=DLR_REBASED;
        }
    }
    Dlr_Hold(g,m,DLR_CONFIRM_STATUS);
}
#endif
