#include "mechanical_dob_monitor.h"
#if defined(FOC_DOB_SHORT_LOW_RECOVERY)
#include "dob_short_low_recovery.h"
DobLowRecovery dob_low_recovery;
#endif
#if defined(FOC_DOB_WARMUP_AB)
volatile uint32_t dob_warmup_tau=DOB_WARMUP_DEFAULT_TAU;
#endif

/* Source: mechanical-bidirectional-fit-1792713255600021200.json, 18 sessions.
 * Mechanical rad/s; dq A. Not absolute J/B/Kt; bias is a model intercept.
 * This module cannot set a reference, controller, PWM, watchdog or protection. */
const MechanicalNormalizedModel mechanical_dob_identified_model={
    .j_over_kt=.0003782906586526162f,.b_over_kt=.0015676864325576986f,
    .coulomb_over_kt=.11945168237076952f,.bias_a=.0005496600325149542f,
    .bandwidth_rad_s=12.566370614359172f,
#if defined(FOC_DOB_CONTACT20_OBSERVE10)
    .min_speed_rad_s=DOB_OBSERVE10_MIN_RAD_S,
#else
    .min_speed_rad_s=2.0943951023931953f,
#endif
    .qualified=1U
};
_Static_assert(sizeof(MechanicalDobMonitorFrame)==44U,"DOB frame ABI");
_Static_assert(sizeof(MechanicalDobMonitor)==856U,"DOB task-only RAM budget");
#if defined(FOC_DOB_SPIKE_ADMISSION)
DobCurrentAdmission dob_current_admission;
#endif
#if defined(FOC_DOB_SATURATION_CONTINUE)
DobSaturationAudit dob_saturation_audit;
#endif

static void begin_write(MechanicalDobMonitor *s){++s->version;KaSync_Barrier();}
static void end_write(MechanicalDobMonitor *s){KaSync_Barrier();++s->version;}
#if defined(FOC_DOB_NORMAL_CONTROL)
#include <stddef.h>
#include <string.h>
void MechanicalDobMonitor_Rearm(MechanicalDobMonitor *s)
{
#if defined(FOC_DOB_SATURATION_CONTINUE)
    dob_saturation_audit=(DobSaturationAudit){0};
#endif
    /* Never transiently publish version=0 during a whole-struct assignment.
     * The odd version remains visible until all session payload is cleared. */
    begin_write(s);
#if defined(FOC_DOB_SHORT_LOW_RECOVERY)
    dob_low_recovery=(DobLowRecovery){0};
#endif
    memset(s,0,offsetof(MechanicalDobMonitor,version));
    size_t tail=offsetof(MechanicalDobMonitor,version)+sizeof(s->version);
    memset((unsigned char *)s+tail,0,sizeof(*s)-tail);
    end_write(s);
}
#endif
void MechanicalDobMonitor_Lifecycle(MechanicalDobMonitor *s,uint8_t running,uint8_t fault)
{
    if (fault) {
        if (s->frozen==DOB_SHADOW_FAULT) return;
        begin_write(s);s->running=0;s->frozen=DOB_SHADOW_FAULT;
        MechanicalDob_Reset(&s->observer,DOB_SHADOW_FAULT);
#if defined(FOC_DOB_SHORT_LOW_RECOVERY)
        Dlr_After(&dob_low_recovery,s,0,0,0);
#endif
#if defined(FOC_DOB_SPIKE_ADMISSION)
        dob_current_admission.decision=DCA_STOP;
#endif
        s->current.valid=0;s->current.disturbance_a=0;s->current.status=DOB_SHADOW_FAULT;end_write(s);return;
    }
    if (!running) {
        if (!s->running) return;
        begin_write(s);s->running=0;s->frozen=DOB_MONITOR_OFF;
        MechanicalDob_Reset(&s->observer,DOB_MONITOR_OFF);
#if defined(FOC_DOB_SHORT_LOW_RECOVERY)
        Dlr_After(&dob_low_recovery,s,0,0,0);
#endif
#if defined(FOC_DOB_SPIKE_ADMISSION)
        dob_current_admission.decision=DCA_STOP;
#endif
        s->current.valid=0;s->current.disturbance_a=0;s->current.status=DOB_MONITOR_OFF;end_write(s);return;
    }
    if (s->running || s->frozen) return; /* Single use; no auto re-arm. */
    begin_write(s);s->running=1U;
#if defined(FOC_DOB_SPIKE_ADMISSION)
    dob_current_admission=(DobCurrentAdmission){0};
#endif
    MechanicalDob_Reset(&s->observer,DOB_SHADOW_WARMUP);
    s->current.valid=0;s->current.status=DOB_SHADOW_WARMUP;end_write(s);
}

void MechanicalDobMonitor_Observe(MechanicalDobMonitor *s,uint32_t now,uint32_t enc,
    uint32_t dt,float omega,uint8_t saturated,const MechanicalCurrent *c,uint8_t valid)
{
    if (!s->running || s->frozen) return;
    begin_write(s);
#if defined(FOC_DOB_SHORT_LOW_RECOVERY)
    Dlr_Before(&dob_low_recovery,s,enc,omega);
#endif
    ++s->observations;
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    dob_current_admission.lpf_before=s->abs_id_lpf;
    dob_current_admission.filter_updated=0;
#endif
    uint32_t status=0;
#if defined(FOC_DOB_SATURATION_CONTINUE)
    ++dob_saturation_audit.samples;
    uint32_t limited=(saturated || (valid&&(c->flags&MEC_SATURATED)))?DOB_MONITOR_SATURATED:0U;
    dob_saturation_audit.iq_limited+=(uint32_t)(saturated!=0);
    dob_saturation_audit.voltage_limited+=(uint32_t)(valid&&(c->flags&MEC_SATURATED)!=0);
    /* Actuator saturation is metadata, not corrupted measured current.
     * ALL other source flags, finite/time/sequence checks remain mandatory. */
    if (!valid || !isfinite(omega) || (valid &&
        (!isfinite(c->iq) || !isfinite(c->id) || (c->flags&~(uint32_t)MEC_SATURATED)))) status|=DOB_MONITOR_CURRENT;
#else
    if (!valid || !isfinite(omega) || (valid &&
        (!isfinite(c->iq) || !isfinite(c->id) || c->flags))) status|=DOB_MONITOR_CURRENT;
#endif
    if (!dt || dt>2000U || now-enc>2000U || (valid &&
        (now-c->source_us>200U || c->published_us-c->source_us>100U))) status|=DOB_MONITOR_TIME;
#if !defined(FOC_DOB_SATURATION_CONTINUE)
    if (saturated) status|=DOB_MONITOR_SATURATED;
    if (valid && (c->flags&MEC_SATURATED)) status|=DOB_MONITOR_SATURATED;
#endif
    if (s->have_sample && (enc-s->last_encoder_us!=dt || (valid &&
        (!(uint32_t)(c->seq-s->last_seq) || (uint32_t)(c->seq-s->last_seq)>80U))))
        status|=DOB_MONITOR_SEQUENCE;
    MechanicalDobMonitorFrame f={.sample_us=enc,.adc_seq=valid?c->seq:0,
        .adc_source_us=valid?c->source_us:0,.adc_published_us=valid?c->published_us:0,
        .omega_rad_s=isfinite(omega)?omega:0,.iq_a=valid&&isfinite(c->iq)?c->iq:0,
        .id_a=valid&&isfinite(c->id)?c->id:0};
    if (status) {
#if defined(FOC_DOB_SATURATION_CONTINUE)
        ++dob_saturation_audit.input_resets;
#endif
        MechanicalDob_Reset(&s->observer,status);s->have_sample=0;
#if defined(FOC_DOB_SPIKE_ADMISSION)
        DobAdmit_Invalidate(&dob_current_admission);
#endif
        ++s->rejected_samples;
    } else {
        float seconds=(float)dt*1e-6f;
#if defined(FOC_DOB_SPIKE_ADMISSION)
#if defined(FOC_DOB_ADMISSION_START_GUARD)
        int qualification=DobAdmit_Qualify(&dob_current_admission,enc,dt,omega,
                                          mechanical_dob_identified_model.min_speed_rad_s);
        if(qualification==2){
            MechanicalDob_Reset(&s->observer,DOB_SHADOW_WARMUP);s->have_sample=0;
        }
        /* Pre-arm uses the old current LPF/Id gate for evidence, without the
         * new jump selector. Entry resets/seeds them, so startup transients
         * cannot become either its stale reference or hidden warmup credit. */
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
        if(!qualification){
            /* No pre-arm raw value is silently used to seed a DOB LPF. */
            s->last_encoder_us=enc;s->last_seq=c->seq;
            f.status=DOB_SHADOW_WARMUP;f.valid=0;goto publish;
        }
        int admit=DobAdmit_Push(&dob_current_admission,enc,dt,c->id,c->iq);
#else
        int admit=qualification?DobAdmit_Push(&dob_current_admission,enc,dt,c->id,c->iq):1;
#endif
#else
        int admit=DobAdmit_Push(&dob_current_admission,enc,dt,c->id,c->iq);
#endif
        if(admit<=0){
#if defined(FOC_DOB_SATURATION_CONTINUE)
            ++dob_saturation_audit.current_skips;
#endif
            /* Every physical epoch remains checked for continuity. HOLD is
             * evidence-only invalid, never a repeated/fake current sample. */
            s->last_encoder_us=enc;s->last_seq=c->seq;
            if(admit<0&&s->have_sample){
                MechanicalDob_Reset(&s->observer,DOB_MONITOR_CURRENT);s->have_sample=0;
            }
            ++s->rejected_samples;f.status=DOB_MONITOR_CURRENT;f.valid=0;
            f.iq_matched_a=0;f.disturbance_a=0;goto publish;
        }
        if(admit==3){
            /* A confirmed persistent level is NOT deleted as noise. The
             * unobserved transition timing invalidates the old DOB state. */
            MechanicalDob_Reset(&s->observer,DOB_MONITOR_CURRENT);s->have_sample=0;
        }
#if defined(FOC_DOB_RECOVERABLE_ADMISSION)
        if(admit==4){
            /* Recover from a long data gap with this actual pair; never
             * integrate a guessed current across the hole or latch a run. */
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
            if(s->have_sample)MechanicalDob_Reset(&s->observer,DOB_MONITOR_CURRENT);
#else
            MechanicalDob_Reset(&s->observer,DOB_MONITOR_CURRENT);
#endif
            s->have_sample=0;
        }
#endif
#if defined(FOC_DOB_PERSISTENT_QUALITY)
        uint8_t id_continuous=(uint8_t)(qualification&&admit==1&&s->have_sample);
#endif
#if defined(FOC_DOB_ADMISSION_START_GUARD)
        if(qualification)
#endif
            seconds=(float)dob_current_admission.accepted_gap_us*1e-6f;
        float warmup_before=s->observer.elapsed_s;
#endif
        if (!s->have_sample) {s->iq_lpf=c->iq;s->abs_id_lpf=fabsf(c->id);}
        else {
            float k=seconds/(DOB_MONITOR_CURRENT_TAU_S+seconds);
            s->iq_lpf+=k*(c->iq-s->iq_lpf);
            s->abs_id_lpf+=k*(fabsf(c->id)-s->abs_id_lpf);
        }
        s->last_encoder_us=enc;s->last_seq=c->seq;s->have_sample=1U;
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
        dob_current_admission.filter_updated=1;
#endif
#if defined(FOC_DOB_PERSISTENT_QUALITY)
        uint32_t was_id_bad=dob_current_admission.id_bad_latched;
        int id_bad=qualification?DobAdmit_IdGate(&dob_current_admission,s->abs_id_lpf,
            DOB_MONITOR_MAX_FILTERED_ABS_ID_A,dt,id_continuous):0;
        if(id_bad){
            if(!was_id_bad)MechanicalDob_Reset(&s->observer,DOB_MONITOR_ID);
            else {s->observer.valid=0;s->observer.status=DOB_MONITOR_ID;}
            ++s->rejected_samples;
        } else MechanicalDob_Observe(&s->observer,&mechanical_dob_identified_model,
            s->iq_lpf,omega,seconds,1U,0U);
#else
        if (s->abs_id_lpf>DOB_MONITOR_MAX_FILTERED_ABS_ID_A) {
            MechanicalDob_Reset(&s->observer,DOB_MONITOR_ID);++s->rejected_samples;
        } else MechanicalDob_Observe(&s->observer,&mechanical_dob_identified_model,
            s->iq_lpf,omega,seconds,1U,0U);
#endif
#if defined(FOC_DOB_SPIKE_ADMISSION)
#if defined(FOC_DOB_ADMISSION_START_GUARD)
        if(!qualification&&s->observer.initialized){
            s->observer.elapsed_s=0;s->observer.valid=0;s->observer.status=DOB_SHADOW_WARMUP;
        }
#endif
        if(admit==2&&s->observer.initialized){
            /* Endpoint update over the actual <=2.5ms gap is an explicit
             * bounded approximation, not reconstructed missing data. Neither
             * the held epoch NOR this gap-recovery epoch earns warmup credit. */
            s->observer.elapsed_s=warmup_before;
            s->observer.valid=0;s->observer.status=DOB_MONITOR_CURRENT;
        }
#endif
    }
    f.status=s->observer.status;f.valid=s->observer.valid;
    f.iq_matched_a=status?0:s->iq_lpf;f.disturbance_a=s->observer.disturbance_a;
#if defined(FOC_DOB_SPIKE_ADMISSION)
publish:
#endif
#if defined(FOC_DOB_SHORT_LOW_RECOVERY)
    s->current=f;
#if defined(FOC_DOB_SATURATION_CONTINUE)
    s->current.status|=limited;
#endif
    Dlr_After(&dob_low_recovery,s,enc,omega,valid);
    f=s->current;
#endif
#if defined(FOC_DOB_SATURATION_CONTINUE)
    /* Keep the limited tag even through warmup/quarantine, so the independent
     * feedback adapter follows its ORIGINAL hold/fade/expiry, never fresh FF. */
    f.status|=limited;
    if(limited&&f.valid)++dob_saturation_audit.limited_valid;
    if(f.status&DOB_SHADOW_WARMUP)++dob_saturation_audit.warmup_frames;
#endif
    s->current=f;
    if (f.valid) {
        ++s->valid_samples;
        if (fabsf(f.disturbance_a)>s->disturbance_abs_peak) s->disturbance_abs_peak=fabsf(f.disturbance_a);
        if (omega>0) {++s->positive_n;s->positive_sum+=f.disturbance_a;}
        else {++s->negative_n;s->negative_sum+=f.disturbance_a;}
    }
    if (!s->count || enc-s->last_stored_us>=DOB_MONITOR_RECORD_US) {
        s->frames[s->head]=f;s->head=(s->head+1U)%DOB_MONITOR_CAPACITY;
        ++s->count;s->last_stored_us=enc;
    }
    end_write(s);
}

uint8_t MechanicalDobMonitor_Read(const MechanicalDobMonitor *s,MechanicalDobMonitorView *v)
{
    for (unsigned attempt=0;attempt<2U;++attempt) {
        uint32_t version=s->version;if (version&1U) continue;
        KaSync_Barrier();
        MechanicalDobMonitorView copy={.current=s->current,.running=s->running,.frozen=s->frozen,
            .observations=s->observations,.valid_samples=s->valid_samples,.rejected_samples=s->rejected_samples,
            .max_compute_us=s->max_compute_us,.disturbance_abs_peak=s->disturbance_abs_peak,
            .positive_mean=s->positive_n?s->positive_sum/(float)s->positive_n:0,
            .negative_mean=s->negative_n?s->negative_sum/(float)s->negative_n:0,.abs_id_lpf=s->abs_id_lpf};
        KaSync_Barrier();if (version==s->version) {*v=copy;return 1U;}
    }
    return 0U; /* No IRQ masking or unbounded spin. */
}
