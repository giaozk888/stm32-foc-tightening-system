#ifndef DOB_CURRENT_ADMISSION_H
#define DOB_CURRENT_ADMISSION_H
#include <stdint.h>
#include <math.h>
/* dq A at the ~1 kHz observer, NOT ADC counts or safety thresholds.
 * Historical classifier: initial Id adjacent-jump P95=.144 A, excursion=.585 A.
 * DIRECT profile uses the user's explicit 0.100 A exclusion threshold instead;
 * neither policy proves that excluded physical current was measurement noise. */
#ifndef DOB_ADMIT_JUMP_A
#if defined(FOC_DOB_DIRECT_JUMP_REJECT)
#define DOB_ADMIT_JUMP_A .100f
#else
#define DOB_ADMIT_JUMP_A .25f
#endif
#endif
#ifndef DOB_ADMIT_RETURN_A
#define DOB_ADMIT_RETURN_A .15f
#endif
#ifndef DOB_ADMIT_CONFIRM_A
#define DOB_ADMIT_CONFIRM_A .05f
#endif
#define DOB_ADMIT_MAX_HOLD_US 2500U
#define DOB_ADMIT_MAX_CONSEC_HOLDS 2U
#define DOB_ADMIT_WINDOW_SAMPLES 32U
#define DOB_ADMIT_MAX_WINDOW_HOLDS 4U
#if defined(FOC_DOB_RECOVERABLE_ADMISSION)
/* Observer-only missing-data bound, NOT an encoder/control watchdog. The
 * existing observer accepts dt <=10ms. Longer gaps reset/reseed recoverably;
 * exclusions never consume a count/rate budget or latch the session. */
#define DOB_ADMIT_RECOVERABLE_GAP_US 10000U
#endif
#if defined(FOC_DOB_PERSISTENT_QUALITY)
/* Observer quality only, NOT current-loop or protection settings. */
#ifndef DOB_ADMIT_JUMP_CONFIRM_POINTS
#define DOB_ADMIT_JUMP_CONFIRM_POINTS 3U
#endif
#ifndef DOB_ID_BAD_CONFIRM_US
#define DOB_ID_BAD_CONFIRM_US 20000U
#endif
_Static_assert(DOB_ADMIT_JUMP_CONFIRM_POINTS>=2U,"Multi-point confirmation required");
_Static_assert(DOB_ID_BAD_CONFIRM_US>0U,"Positive Id confirmation time required");
#endif
#if defined(FOC_DOB_ADMISSION_START_GUARD)
#define DOB_ADMIT_ARM_CONFIRM_US 50000U
#endif
enum { DCA_NORMAL=0,DCA_SEED,DCA_SUSPECT,DCA_SPIKE_RETURN,DCA_TRANSITION,
       DCA_UNRESOLVED,DCA_BLOCKED,DCA_QUALITY,DCA_STOP,DCA_PREARM,
       DCA_DIRECT_REJECT,DCA_GAP_RECOVERY,DCA_GAP_RESEED,DCA_GAP_STALE,
       DCA_JUMP_PENDING,DCA_RUN_REJECT,DCA_QUALITY_WAIT,DCA_QUALITY_RETURN,
       DCA_QUALITY_LEVEL,DCA_QUALITY_SEED };
enum { DCA_EXIT_NONE=0,DCA_EXIT_TIME,DCA_EXIT_CONSECUTIVE,DCA_EXIT_RATE,DCA_EXIT_INPUT };
typedef struct {
    float reference_id,reference_iq,candidate_id,candidate_iq;
    uint32_t seeded,pending,pending_us,blocked,decision;
    uint32_t samples,passed,suspects,isolated,transitions,unresolved,held;
    uint32_t consecutive_holds,window_samples,window_holds,budget_exits;
    uint32_t last_accepted_us,accepted_gap_us;
    uint32_t exit_reason;
#if defined(FOC_DOB_ADMISSION_START_GUARD)
    uint32_t armed,qualify_us,prearm_samples,arm_us;
    int32_t qualify_sign;
#endif
#if defined(FOC_DOB_RECOVERABLE_ADMISSION)
    uint32_t gap_stale,gap_resets,recoveries;
#endif
#if defined(FOC_DOB_PERSISTENT_QUALITY)
    uint32_t jump_run,jump_max_run,jump_pending_samples;
    uint32_t id_bad_us,id_bad_peak_us,id_bad_latched,id_bad_entries,id_bad_recoveries,id_above_previous;
#endif
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    float raw_id,raw_iq,raw_delta_id,raw_delta_iq,lpf_before;
    uint32_t raw_have,quality_reason,quality_recoveries,level_confirms,seed_confirms,filter_updated;
#endif
} DobCurrentAdmission;
extern DobCurrentAdmission dob_current_admission;
static inline float DobAdmit_Distance(float id,float iq,float old_id,float old_iq){
    return fmaxf(fabsf(id-old_id),fabsf(iq-old_iq));
}
/* Only clears continuity after an EXISTING quality failure. Never clears a
 * latched admission exit, its counters, or any motor protection. */
static inline void DobAdmit_Invalidate(DobCurrentAdmission *s){
    s->seeded=0;s->pending=0;s->consecutive_holds=0;s->decision=DCA_QUALITY;
#if defined(FOC_DOB_RECOVERABLE_ADMISSION)
    s->gap_stale=0;
#endif
#if defined(FOC_DOB_PERSISTENT_QUALITY)
#if !defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    s->jump_run=0;s->id_bad_us=0;s->id_above_previous=0;
#else
    /* Rejected source evidence cannot alter the Id timer/baseline. The next
     * qualified recovery explicitly breaks continuity before updating it. */
    s->jump_run=0;s->raw_have=0;s->quality_reason=16U;
    s->raw_delta_id=s->raw_delta_iq=0;
#endif
#endif
#if defined(FOC_DOB_ADMISSION_START_GUARD)
    if(!s->armed){s->qualify_us=0;s->qualify_sign=0;}
#endif
}
#if defined(FOC_DOB_ADMISSION_START_GUARD)
/* Called only AFTER original source/sequence/saturation checks. Minimum speed
 * is the existing qualified-model value, NOT a new protection threshold.
 * One-way arming; never clears an armed-session exit or retries admission. */
static inline int DobAdmit_Qualify(DobCurrentAdmission *s,uint32_t now,uint32_t dt,
                                  float omega,float min_speed){
    if(s->armed)return 1;
    ++s->prearm_samples;s->decision=DCA_PREARM;
    int32_t sign=omega>0?1:-1;
    if(!isfinite(omega)||!isfinite(min_speed)||min_speed<=0||fabsf(omega)<min_speed||!dt||dt>2000U){
        s->qualify_us=0;s->qualify_sign=0;return 0;
    }
    if(sign!=s->qualify_sign){s->qualify_us=0;s->qualify_sign=sign;}
    s->qualify_us+=dt;
    if(s->qualify_us<DOB_ADMIT_ARM_CONFIRM_US)return 0;
    s->armed=1;s->arm_us=now;s->seeded=0;s->pending=0;
#if defined(FOC_DOB_PERSISTENT_QUALITY)
    s->jump_run=0;s->id_bad_us=0;s->id_bad_latched=0;s->id_above_previous=0;
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    s->raw_have=0;
#endif
#endif
    return 2; /* Reset/reseed observer at the first qualified actual pair. */
}
#endif
#if defined(FOC_DOB_PERSISTENT_QUALITY)
/* Positive return means model domain remains unavailable. Only a continuous
 * sequence of actual admitted adjacent epochs earns time. Missing/recovery
 * intervals clear the pending timer, not an already confirmed condition.
 * Below/equal-threshold qualified evidence clears the condition; observer
 * state was reset on entry and must complete its usual fresh warmup. */
static inline int DobAdmit_IdGate(DobCurrentAdmission *s,float filtered_abs_id,
                                 float limit,uint32_t dt,uint8_t continuous){
    if(!continuous){s->id_bad_us=0;s->id_above_previous=0;}
    if(filtered_abs_id<=limit){
        if(s->id_bad_latched)++s->id_bad_recoveries;
        s->id_bad_us=0;s->id_bad_latched=0;s->id_above_previous=0;return 0;
    }
    if(continuous&&s->id_above_previous){
        uint32_t remaining=UINT32_MAX-s->id_bad_us;
        s->id_bad_us+=dt<remaining?dt:remaining;
        if(s->id_bad_us>s->id_bad_peak_us)s->id_bad_peak_us=s->id_bad_us;
    }
    s->id_above_previous=1;
    if(s->id_bad_us>=DOB_ID_BAD_CONFIRM_US&&!s->id_bad_latched){
        s->id_bad_latched=1;++s->id_bad_entries;
    }
    return (int)s->id_bad_latched;
}
#endif
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
#include "dob_id_pre_lpf_quality.h"
#endif
/* Recoverable opt-in: 1=actual pair, 2=short-gap recovery (invalid epoch),
 * 4=long-gap actual reseed (fresh warmup), 0=skip, -2=quality/long-gap reset.
 * No count/rate latch. The legacy profiles below retain their original policy:
 * 1=this actual pair; 2=actual return pair after one discarded candidate;
 * 3=persistent transition (reset observer, then admit current pair); 0=wait;
 * -1=latched diagnostic exit until the next explicitly reset session/MCU.
 * No substitution, clipping, interpolation, controller or actuator access. */
/* DIRECT variant: 0=excluded NOW (not pending confirmation); 2=accepted real
 * pair after a gap, invalid recovery epoch, NOT confirmed-spike classification.
 * It never returns 3 and never rebases to a rejected persistent new level. */
static inline int DobAdmit_Push(DobCurrentAdmission *s,uint32_t now,uint32_t dt,float id,float iq){
    ++s->samples;
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    return DobIdQuality_Push(s,now,dt,id,iq);
#elif defined(FOC_DOB_RECOVERABLE_ADMISSION)
    /* candidate_{id,iq} are PREVIOUS RAW finite/source-qualified values in
     * this opt-in ABI, not values supplied to either LPF or model. The old
     * reference_{id,iq} remain the last admitted values for inspection. */
    if(!isfinite(id)||!isfinite(iq)||!dt||dt>2000U){
        DobAdmit_Invalidate(s);s->exit_reason=DCA_EXIT_INPUT;return -2;
    }
    s->exit_reason=DCA_EXIT_NONE;
    if(!s->seeded){
        s->candidate_id=id;s->candidate_iq=iq;
        s->reference_id=id;s->reference_iq=iq;s->seeded=1;
        s->last_accepted_us=now;s->accepted_gap_us=dt;
        s->decision=DCA_SEED;++s->passed;return 1;
    }
    float jump=DobAdmit_Distance(id,iq,s->candidate_id,s->candidate_iq);
    s->candidate_id=id;s->candidate_iq=iq; /* Even an excluded RAW pair. */
    uint32_t gap=now-s->last_accepted_us;
    s->accepted_gap_us=gap;
    int newly_stale=0;
    if((!gap||gap>DOB_ADMIT_RECOVERABLE_GAP_US)&&!s->gap_stale){
        s->gap_stale=1;++s->gap_resets;newly_stale=1;
    }
    int exclude=jump>DOB_ADMIT_JUMP_A;
#if defined(FOC_DOB_PERSISTENT_QUALITY)
    if(exclude){
        if(s->jump_run<UINT32_MAX)++s->jump_run;
        if(s->jump_run>s->jump_max_run)s->jump_max_run=s->jump_run;
        ++s->suspects;
        exclude=s->jump_run>=DOB_ADMIT_JUMP_CONFIRM_POINTS;
        if(!exclude)++s->jump_pending_samples;
    }else s->jump_run=0;
#endif
    if(exclude){
#if defined(FOC_DOB_PERSISTENT_QUALITY)
        ++s->held;++s->consecutive_holds;s->id_bad_us=0;s->id_above_previous=0;
        s->decision=newly_stale?DCA_GAP_STALE:DCA_RUN_REJECT;
#else
        ++s->suspects;++s->held;++s->consecutive_holds;
        s->decision=newly_stale?DCA_GAP_STALE:DCA_DIRECT_REJECT;
#endif
        /* No LPF update, reset, or warmup credit for a short-gap skip. Only
         * the first genuinely long gap requests a reset, never a latch. */
        return newly_stale?-2:0;
    }
    int result=s->gap_stale?4:s->consecutive_holds?2:1;
    s->decision=result==4?DCA_GAP_RESEED:result==2?DCA_GAP_RECOVERY:DCA_NORMAL;
#if defined(FOC_DOB_PERSISTENT_QUALITY)
    if(result==1&&s->jump_run)s->decision=DCA_JUMP_PENDING;
#endif
    if(result!=1)++s->recoveries;
    if(result==4)s->accepted_gap_us=dt; /* No integration across a long hole. */
    s->reference_id=id;s->reference_iq=iq;s->last_accepted_us=now;
    s->gap_stale=0;s->consecutive_holds=0;++s->passed;return result;
#else
    if(s->blocked){s->decision=DCA_BLOCKED;return -1;}
    if(!isfinite(id)||!isfinite(iq)||!dt||dt>2000U||!isfinite(DOB_ADMIT_JUMP_A)||DOB_ADMIT_JUMP_A<=0
#if !defined(FOC_DOB_DIRECT_JUMP_REJECT)
       || !(DOB_ADMIT_RETURN_A>0&&DOB_ADMIT_RETURN_A<=DOB_ADMIT_JUMP_A&&
         DOB_ADMIT_CONFIRM_A>0&&DOB_ADMIT_CONFIRM_A<=DOB_ADMIT_JUMP_A)
#endif
       ){
        s->exit_reason=DCA_EXIT_INPUT;goto blocked;
    }
    if(s->window_samples==DOB_ADMIT_WINDOW_SAMPLES){s->window_samples=0;s->window_holds=0;}
    ++s->window_samples;
    int result=1;
    s->decision=DCA_NORMAL;
    if(!s->seeded){s->decision=DCA_SEED;s->accepted_gap_us=dt;}
    else{
        uint32_t gap=now-s->last_accepted_us;
        if(!gap||gap>DOB_ADMIT_MAX_HOLD_US){s->exit_reason=DCA_EXIT_TIME;goto blocked;}
        s->accepted_gap_us=gap;
        float old= DobAdmit_Distance(id,iq,s->reference_id,s->reference_iq);
#if defined(FOC_DOB_DIRECT_JUMP_REJECT)
        /* Immediate whole-pair exclusion versus the last ACCEPTED pair.
         * Never install an excluded pair as reference/candidate and never
         * retroactively call it a confirmed physical spike. No return test. */
        if(old>DOB_ADMIT_JUMP_A){s->decision=DCA_DIRECT_REJECT;++s->suspects;goto hold;}
        if(s->consecutive_holds){s->decision=DCA_GAP_RECOVERY;result=2;}
#else
        if(!s->pending){
            if(old>DOB_ADMIT_JUMP_A){
                s->candidate_id=id;s->candidate_iq=iq;s->pending=1;s->pending_us=now;
                s->decision=DCA_SUSPECT;++s->suspects;goto hold;
            }
        }else{
            float candidate=DobAdmit_Distance(id,iq,s->candidate_id,s->candidate_iq);
            if(old<=DOB_ADMIT_RETURN_A){s->decision=DCA_SPIKE_RETURN;++s->isolated;result=2;}
            else if(candidate<=DOB_ADMIT_CONFIRM_A&&candidate<old){
                s->decision=DCA_TRANSITION;++s->transitions;result=3;
            }else{s->decision=DCA_UNRESOLVED;++s->unresolved;goto hold;}
        }
#endif
    }
    s->reference_id=id;s->reference_iq=iq;s->seeded=1;s->pending=0;
    s->last_accepted_us=now;s->consecutive_holds=0;++s->passed;return result;
hold:
    ++s->held;++s->consecutive_holds;++s->window_holds;
    if(s->consecutive_holds>=DOB_ADMIT_MAX_CONSEC_HOLDS){s->exit_reason=DCA_EXIT_CONSECUTIVE;goto blocked;}
    if(s->window_holds>DOB_ADMIT_MAX_WINDOW_HOLDS){s->exit_reason=DCA_EXIT_RATE;goto blocked;}
    return 0;
blocked:
    s->blocked=1;s->decision=DCA_BLOCKED;++s->budget_exits;return -1;
#endif
}
#endif
