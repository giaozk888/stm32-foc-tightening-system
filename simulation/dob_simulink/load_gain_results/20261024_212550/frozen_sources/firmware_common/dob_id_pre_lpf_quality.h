#ifndef DOB_ID_PRE_LPF_QUALITY_H
#define DOB_ID_PRE_LPF_QUALITY_H
/* Included only after DobCurrentAdmission/DobAdmit_Distance. Task-only DOB
 * quality, no actuator/FOC references. A jump is suspicion, not proof of an
 * impossible physical current. Do not substitute an unverified absolute Id
 * limit (Iq command limits and filtered-Id model bounds are NOT raw bounds).
 * Existing finite/source/ADC/current protection checks remain independent. */
enum {
    DQ_SEED=1U,DQ_ID_JUMP=2U,DQ_IQ_JUMP=4U,DQ_WAIT=8U,
    DQ_SOURCE=16U,DQ_GAP=32U,DQ_RETURN=64U,DQ_LEVEL=128U,DQ_FIRST=256U
};
static inline void DobIdQuality_Raw(DobCurrentAdmission *s,float id,float iq){
    s->raw_delta_id=s->raw_have?id-s->raw_id:0;
    s->raw_delta_iq=s->raw_have?iq-s->raw_iq:0;
    s->raw_id=id;s->raw_iq=iq;s->raw_have=1;
}
static inline int DobIdQuality_Push(DobCurrentAdmission *s,uint32_t now,
                                   uint32_t dt,float id,float iq){
    if(!isfinite(id)||!isfinite(iq)||!dt||dt>2000U){
        s->seeded=0;s->pending=0;s->jump_run=0;s->raw_have=0;
        s->raw_delta_id=s->raw_delta_iq=0;s->quality_reason=DQ_SOURCE;
        s->exit_reason=DCA_EXIT_INPUT;return -2;
    }
    DobIdQuality_Raw(s,id,iq);s->exit_reason=DCA_EXIT_NONE;s->quality_reason=0;
    uint32_t gap=s->seeded?now-s->last_accepted_us:dt;
    int newly_stale=0;
    if(s->seeded&&(!gap||gap>DOB_ADMIT_RECOVERABLE_GAP_US)&&!s->gap_stale){
        s->gap_stale=1;++s->gap_resets;newly_stale=1;
    }
    int accepted=0,was_pending=(int)s->pending;
    if(s->seeded&&DobAdmit_Distance(id,iq,s->reference_id,s->reference_iq)<=DOB_ADMIT_JUMP_A){
        /* A real return near the trusted level does not have to jump back
         * over a contaminated RAW baseline. Accept this actual return pair,
         * never the stored suspect; mark the recovery epoch invalid below. */
        accepted=1;
        s->quality_reason=was_pending?DQ_RETURN:0;
        s->decision=was_pending?DCA_QUALITY_RETURN:DCA_NORMAL;
    }else{
        if(!s->seeded)s->quality_reason=DQ_SEED;
        else{
            if(fabsf(id-s->reference_id)>DOB_ADMIT_JUMP_A)s->quality_reason|=DQ_ID_JUMP;
            if(fabsf(iq-s->reference_iq)>DOB_ADMIT_JUMP_A)s->quality_reason|=DQ_IQ_JUMP;
        }
        /* Quarantine from the FIRST suspicion. Coherence is measured versus
         * the fixed first candidate of a cluster, not a drifting baseline.
         * Disagreement restarts the cluster; nothing is replayed to the LPF. */
        if(!s->pending||DobAdmit_Distance(id,iq,s->candidate_id,s->candidate_iq)>DOB_ADMIT_JUMP_A){
            s->candidate_id=id;s->candidate_iq=iq;s->pending_us=now;s->jump_run=1;
        }else if(s->jump_run<DOB_ADMIT_JUMP_CONFIRM_POINTS)++s->jump_run;
        s->pending=1;
        if(s->jump_run>s->jump_max_run)s->jump_max_run=s->jump_run;
        if(s->jump_run>=DOB_ADMIT_JUMP_CONFIRM_POINTS){
            accepted=1;
            s->decision=s->seeded?DCA_QUALITY_LEVEL:DCA_QUALITY_SEED;
            s->quality_reason|=s->seeded?DQ_LEVEL:DQ_FIRST;
            if(s->seeded)++s->level_confirms;else ++s->seed_confirms;
        }
    }
    if(!accepted){
        ++s->suspects;++s->held;++s->consecutive_holds;++s->jump_pending_samples;
        s->quality_reason|=DQ_WAIT;
        if(s->gap_stale)s->quality_reason|=DQ_GAP;
        s->decision=newly_stale?DCA_GAP_STALE:DCA_QUALITY_WAIT;
        /* No LPF, accepted reference/time, Id timer/baseline, warmup or valid
         * statistics update. The long-gap reset request is recoverable, not
         * a consecutive/rate session latch. Pending storage is not model data. */
        return newly_stale?-2:0;
    }
    int result=s->gap_stale?4:s->seeded&&was_pending?2:1;
    if(result==4){s->decision=DCA_GAP_RESEED;s->quality_reason|=DQ_GAP;}
    if(result!=1){++s->recoveries;++s->quality_recoveries;}
    s->accepted_gap_us=result==4?dt:gap;
    s->reference_id=id;s->reference_iq=iq;s->last_accepted_us=now;s->seeded=1;
    s->pending=0;s->jump_run=0;s->consecutive_holds=0;s->gap_stale=0;
    ++s->passed;return result;
}
#endif
