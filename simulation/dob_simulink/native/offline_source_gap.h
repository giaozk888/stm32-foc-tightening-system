#ifndef DOB_OFFLINE_SOURCE_GAP_H
#define DOB_OFFLINE_SOURCE_GAP_H
/* EXPERIMENTAL simulation-only adapter, never included by MCU firmware.
 * Only explicit current-source unavailability, not time/encoder/OC faults.
 * No interpolation or observer integration through missing intervals. */
#include "mechanical_dob_monitor.h"
#define OSG_MAX_GAP_US 5000U
#define OSG_MAX_SPEED_CHANGE_RAD_S .5f /* model-quality bound, NOT a safety trip */
enum { OSG_NORMAL,OSG_HOLD,OSG_CONFIRM,OSG_REBASED,OSG_EXPIRED,OSG_UNSAFE };
enum { OSG_STATUS_HOLD=4096U,OSG_STATUS_CONFIRM=8192U,OSG_STATUS_EXPIRED=16384U };
typedef struct {
    uint32_t pending,expired,confirm,anchor_us,anchor_seq,confirm_us,confirm_seq;
    uint32_t mode,holds,recovered,long_resets;
    float candidate_id,candidate_iq;
} OfflineSourceGap;
static inline void Osg_Publish(MechanicalDobMonitor *m,uint32_t enc,uint32_t status){
    ++m->version;++m->observations;++m->rejected_samples;
    m->current.sample_us=enc;m->current.valid=0;m->current.status=status;
    m->current.disturbance_a=m->observer.disturbance_a;
    dob_current_admission.filter_updated=0;
    dob_current_admission.lpf_before=m->abs_id_lpf;
    ++m->version;
}
static inline void Osg_Expire(OfflineSourceGap *g,MechanicalDobMonitor *m){
    if(!g->expired){
        MechanicalDob_Reset(&m->observer,DOB_MONITOR_CURRENT);m->have_sample=0;
        DobAdmit_Invalidate(&dob_current_admission);g->expired=1;++g->long_resets;
    }
    g->mode=OSG_EXPIRED;
}
static inline void OfflineSourceGap_Observe(OfflineSourceGap *g,MechanicalDobMonitor *m,
    uint32_t now,uint32_t enc,uint32_t dt,float omega,uint8_t saturated,
    const MechanicalCurrent *c,uint8_t valid){
    if(!m->running||m->frozen){g->pending=0;g->mode=OSG_UNSAFE;return;}
    int timing=dt==1000U&&now-enc<=2000U&&isfinite(omega);
    int metadata=timing&&!saturated&&!c->flags&&
        (!valid||(isfinite(c->id)&&isfinite(c->iq)&&now-c->source_us<=200U&&
                  c->published_us-c->source_us<=100U));
    if(!metadata){
        g->pending=0;g->mode=OSG_UNSAFE;
        MechanicalDobMonitor_Observe(m,now,enc,dt,omega,saturated,c,valid);return;
    }
    if(g->pending&&!g->expired&&(!m->have_sample||!m->observer.initialized))g->pending=0;
    if(!valid){
        if(!g->pending){
            if(!m->have_sample||!m->observer.valid||!dob_current_admission.seeded||
               dob_current_admission.pending||dob_current_admission.id_bad_latched){
                g->mode=OSG_UNSAFE;
                MechanicalDobMonitor_Observe(m,now,enc,dt,omega,saturated,c,valid);return;
            }
            g->pending=1;g->expired=g->confirm=0;
            g->anchor_us=m->last_encoder_us;g->anchor_seq=m->last_seq;
        }
        if(enc-g->anchor_us>OSG_MAX_GAP_US)Osg_Expire(g,m);
        else if(!g->expired)g->mode=OSG_HOLD;
        ++g->holds;
        Osg_Publish(m,enc,g->expired?OSG_STATUS_EXPIRED:OSG_STATUS_HOLD);return;
    }
    if(!g->pending){
        g->mode=OSG_NORMAL;
        MechanicalDobMonitor_Observe(m,now,enc,dt,omega,saturated,c,valid);return;
    }
    if(enc-g->anchor_us>OSG_MAX_GAP_US)Osg_Expire(g,m);
    if(g->expired){
        g->pending=0;
        MechanicalDobMonitor_Observe(m,now,enc,dt,omega,saturated,c,valid);return;
    }
    uint32_t seq_delta=c->seq-g->anchor_seq;
    int coherent=seq_delta&&seq_delta<=100U&&
        fabsf(omega)>=mechanical_dob_identified_model.min_speed_rad_s&&
        omega*m->current.omega_rad_s>0&&
        fabsf(omega-m->current.omega_rad_s)<=OSG_MAX_SPEED_CHANGE_RAD_S&&
        DobAdmit_Distance(c->id,c->iq,dob_current_admission.reference_id,
                          dob_current_admission.reference_iq)<=DOB_ADMIT_JUMP_A;
    if(g->confirm)coherent=coherent&&enc-g->confirm_us==dt&&
        c->seq-g->confirm_seq>0&&c->seq-g->confirm_seq<=80U&&
        DobAdmit_Distance(c->id,c->iq,g->candidate_id,g->candidate_iq)<=DOB_ADMIT_JUMP_A;
    if(!coherent){
        Osg_Expire(g,m);g->pending=0;g->mode=OSG_UNSAFE;
        MechanicalDobMonitor_Observe(m,now,enc,dt,omega,saturated,c,valid);return;
    }
    if(!g->confirm){
        g->candidate_id=c->id;g->candidate_iq=c->iq;
        g->confirm_us=enc;g->confirm_seq=c->seq;g->confirm=1;g->mode=OSG_CONFIRM;
    }else{
        /* Two real coherent endpoints re-establish continuity. This endpoint
         * is NOT an LPF/model update or valid estimate. Zero missing-time
         * warmup/Id dwell/integration credit; no old suspect is replayed. */
        m->last_encoder_us=enc;m->last_seq=c->seq;
        dob_current_admission.last_accepted_us=enc;
        dob_current_admission.reference_id=c->id;dob_current_admission.reference_iq=c->iq;
        dob_current_admission.accepted_gap_us=dt;
        dob_current_admission.id_bad_us=0;
        dob_current_admission.id_above_previous=0;
        g->pending=0;g->mode=OSG_REBASED;++g->recovered;
    }
    Osg_Publish(m,enc,OSG_STATUS_CONFIRM);
}
#endif
