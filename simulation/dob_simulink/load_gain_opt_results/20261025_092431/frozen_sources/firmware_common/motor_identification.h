#ifndef MOTOR_IDENTIFICATION_H
#define MOTOR_IDENTIFICATION_H
#include <stdint.h>
#include <math.h>
#include <string.h>
#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
#include <stdatomic.h>
#endif

/* Diagnostic admission/quality bounds only. Never controller/protection gains. */
#define MID_ROWS 32U
#define MID_CURRENT_MAX_A 0.20f
#if defined(FOC_IDENT_CURRENT_REJECT_ENABLE)
/* Bounded diagnostic tolerance, independent hard protection is unchanged. */
#define MID_MAX_CURRENT_REJECTS 16U
#define MID_CURRENT_REJECT_RUN_LIMIT 3U
#endif
#if defined(FOC_IDENT_RS_REJECT_COUNT_ONLY) && \
    (!defined(FOC_IDENT_CURRENT_REJECT_ENABLE) || !defined(FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT))
#error Rs reject count-only requires sample rejection and total-stop-disabled policy
#endif
#define MID_VOLTAGE_MAX_V 0.20f
#define MID_SPEED_MAX_RPM 2.0f
#define MID_TRAVEL_MAX_DEG 0.10f
#ifndef MID_TRAVEL_EXIT_ENABLE
#define MID_TRAVEL_EXIT_ENABLE 1
#endif
#define MID_RS_DURATION_US 400000U
#define MID_STEP_US 100000U
#define MID_L_DURATION_US 104000U
#define MID_CAPTURE_START_US 99800U
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
/* Zero voltage for 100ms, then <=4ms at 50mV. Never an automatic sweep. */
#define MID_VOLTAGE_STEP_MV 50U
_Static_assert(MID_VOLTAGE_STEP_MV<=200U,"Keep existing diagnostic voltage bound");
#endif
/* Software timestamp quality limit only; not ADC/FOC watchdog timing.
 * Historical builds stay 55us. The independent Rs-only candidate selects 100. */
#ifndef MID_RS_SOFT_DT_MAX_US
#define MID_RS_SOFT_DT_MAX_US 55U
#endif
#if defined(FOC_IDENT_L_RS_ADMISSION_ENABLE)
#if !defined(FOC_IDENT_RS_REJECT_COUNT_ONLY) || !defined(FOC_IDENT_RS_GAP_COUNT_ONLY)
#error L-axis admission adaptation requires the complete Rs count-only policies
#endif
#define MID_L_SOFT_DT_MAX_US MID_RS_SOFT_DT_MAX_US
#else
#define MID_L_SOFT_DT_MAX_US 55U
#endif
#if defined(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
/* Estimator-only admission: at most two consecutive held physical pairs,
 * every skipped seq explained by discriminator hold count. Historical builds
 * cap total skips at 16; opt-in count-only Rs keeps totals as diagnostics.
 * Never extend the fixed 400ms duration or interpolate missing current. */
#define MID_RS_MAX_SKIPPED_PAIRS 16U
#define MID_RS_MAX_CONSEC_SKIPPED 2U
#endif
#if defined(FOC_IDENT_RS_GAP_COUNT_ONLY) && !defined(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
#error Rs gap count-only policy requires explained-gap admission
#endif
enum { MID_NONE, MID_RS, MID_LD, MID_LQ };
enum { MID_IDLE, MID_QUEUED, MID_ACTIVE, MID_DONE, MID_ABORT };
enum { MID_OK, MID_PROTECTION, MID_MOTION, MID_CURRENT, MID_VOLTAGE,
       MID_BAD_DATA, MID_CANCELLED, MID_NOT_READY, MID_TIMING };
typedef struct {
    uint32_t us,seq,pending_before;
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
    uint16_t raw_u,raw_v,tail_cnt,tail_flags;
#else
    float id_ref,iq_ref;
#endif
    float id,iq,vd,vq,angle,speed;
    uint8_t mode,status,reason,reserved;
} MotorIdentFrame;
_Static_assert(sizeof(MotorIdentFrame)==48U,"Binary identification ABI");
#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
/* First failure only. Unsigned deltas intentionally support counter wrap.
 * flags: bit0 sequence gap, bit1 short dt, bit2 long dt.
 * Software reference-owner timestamps, NOT physical ADC aperture timestamps. */
typedef struct {
    uint32_t prev_seq,prev_us,seq,us,delta_seq,delta_us,flags,valid;
    uint32_t adc_seq,frame_seq,pair_us,hold_before,hold_now,path,context_valid;
} MotorIdentTimingFailure;
_Static_assert(sizeof(MotorIdentTimingFailure)==60U,"Timing trace ABI");
#endif
typedef struct {
    MotorIdentFrame rows[MID_ROWS];
    uint32_t count,start_us,last_us,last_seq,encoder_before,pending_before;
    uint32_t arr,ccr4,cr1,rcr,jsqr;
    float initial_angle,current_a;
    uint8_t mode,status,reason,used,prepared,admitting,confirmed_locked,reserved;
#if defined(FOC_IDENT_CURRENT_REJECT_ENABLE)
    MotorIdentFrame first_reject;
    uint32_t current_reject_count,current_good_count;
    uint16_t first_raw_u,first_raw_v;
    uint8_t current_reject_run,max_current_reject_run,sample_rejected,first_reject_valid;
#endif
#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
    MotorIdentTimingFailure timing_failure;
    uint32_t last_hold_count;
#endif
#if defined(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
    uint32_t rs_hold_delta,rs_gap_events,rs_skipped_pairs,rs_max_skipped;
#endif
} MotorIdentification;

#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
static inline void MotorIdent_TimingLatch(MotorIdentification *s,uint32_t now,
    uint32_t seq,uint32_t flags)
{
    MotorIdentTimingFailure *t=&s->timing_failure;
    if (t->valid) return;
    t->prev_seq=s->last_seq;t->prev_us=s->last_us;t->seq=seq;t->us=now;
    t->delta_seq=seq-s->last_seq;t->delta_us=now-s->last_us;t->flags=flags;
    atomic_signal_fence(memory_order_release);t->valid=1U;
}
#endif

static inline uint8_t MotorIdent_Parse(const char *cmd,uint8_t *mode,float *amps)
{
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
    if (!strcmp(cmd,"MOTOR TEST IDENT LDV 50MV LOCKED CONFIRM")) {*mode=MID_LD;*amps=0;}
    else if (!strcmp(cmd,"MOTOR TEST IDENT LQV 50MV LOCKED CONFIRM")) {*mode=MID_LQ;*amps=0;}
    else return 0;
#else
    if (!strcmp(cmd,"MOTOR TEST IDENT RS 50 LOCKED CONFIRM")) {*mode=MID_RS;*amps=.05f;}
    else if (!strcmp(cmd,"MOTOR TEST IDENT RS 75 LOCKED CONFIRM")) {*mode=MID_RS;*amps=.075f;}
    else if (!strcmp(cmd,"MOTOR TEST IDENT RS 100 LOCKED CONFIRM")) {*mode=MID_RS;*amps=.10f;}
    else if (!strcmp(cmd,"MOTOR TEST IDENT LD RS_VALIDATED LOCKED CONFIRM")) {*mode=MID_LD;*amps=.10f;}
    else if (!strcmp(cmd,"MOTOR TEST IDENT LQ RS_VALIDATED LOCKED CONFIRM")) {*mode=MID_LQ;*amps=.10f;}
    else return 0;
#endif
    return 1;
}
static inline void MotorIdent_End(MotorIdentification *s,uint8_t reason)
{ s->reason=reason;s->status=reason ? MID_ABORT : MID_DONE; }
static inline uint8_t MotorIdent_RsAdmission(const MotorIdentification *s)
{
    return (uint8_t)(s->mode==MID_RS
#if defined(FOC_IDENT_L_RS_ADMISSION_ENABLE)
        || s->mode==MID_LD || s->mode==MID_LQ
#endif
    );
}
static inline uint32_t MotorIdent_SoftDtMax(const MotorIdentification *s)
{ return s->mode==MID_RS ? MID_RS_SOFT_DT_MAX_US : MID_L_SOFT_DT_MAX_US; }
#if defined(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
static inline uint8_t MotorIdent_RsExplainedGap(MotorIdentification *s,
    uint32_t now,uint32_t seq)
{
    uint32_t ds=seq-s->last_seq,dt=now-s->last_us;
    if (!MotorIdent_RsAdmission(s) || ds<2U || ds>MID_RS_MAX_CONSEC_SKIPPED+1U ||
        s->rs_hold_delta!=ds-1U || dt<45U*ds || dt>55U*ds
#if !defined(FOC_IDENT_RS_GAP_COUNT_ONLY)
        || s->rs_skipped_pairs>MID_RS_MAX_SKIPPED_PAIRS-(ds-1U)
#endif
        ) return 0U;
    /* Rs steady-state estimator only: still reject unexplained/long gaps.
     * Count every explained hold; never extend duration or synthesize a row. */
    ++s->rs_gap_events;s->rs_skipped_pairs+=ds-1U;
    if (ds-1U>s->rs_max_skipped) s->rs_max_skipped=ds-1U;
    return 1U;
}
#endif
/* ADC owner only after admission. Stop/fault never clears used or re-arms. */
static inline uint8_t MotorIdent_Reference(MotorIdentification *s,uint32_t now,
    uint32_t seq,float position,float speed,float id,float iq,float *d,float *q)
{
    if (s->status!=MID_ACTIVE) return 1;
    uint32_t elapsed=now-s->start_us;
    uint32_t duration=s->mode==MID_RS ? MID_RS_DURATION_US : MID_L_DURATION_US;
    if (elapsed>=duration) {MotorIdent_End(s,MID_OK);*d=*q=0;return 0;}
    if (!isfinite(position) || !isfinite(speed) || !isfinite(id) || !isfinite(iq))
        MotorIdent_End(s,MID_BAD_DATA);
    else if (
#if MID_TRAVEL_EXIT_ENABLE
        fabsf(position-s->initial_angle)>MID_TRAVEL_MAX_DEG ||
#endif
        fabsf(speed)>MID_SPEED_MAX_RPM)
        MotorIdent_End(s,MID_MOTION);
#if !defined(FOC_IDENT_CURRENT_REJECT_ENABLE)
    else if (fabsf(id)>MID_CURRENT_MAX_A || fabsf(iq)>MID_CURRENT_MAX_A)
        MotorIdent_End(s,MID_CURRENT);
#endif
    else if (s->last_us && ((uint32_t)(seq-s->last_seq)!=1U ||
             (uint32_t)(now-s->last_us)<45U ||
             (uint32_t)(now-s->last_us)>MotorIdent_SoftDtMax(s))
#if defined(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
             && !MotorIdent_RsExplainedGap(s,now,seq)
#endif
             ) {
#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
        MotorIdent_TimingLatch(s,now,seq,
            ((uint32_t)(seq-s->last_seq)!=1U ? 1U : 0U) |
            ((uint32_t)(now-s->last_us)<45U ? 2U : 0U) |
            ((uint32_t)(now-s->last_us)>MotorIdent_SoftDtMax(s) ? 4U : 0U));
#endif
        MotorIdent_End(s,MID_TIMING);
    }
    if (s->status!=MID_ACTIVE) {*d=*q=0;return 0;}
    s->last_us=now;s->last_seq=seq;
#if defined(FOC_IDENT_CURRENT_REJECT_ENABLE)
    s->sample_rejected=(uint8_t)(fabsf(id)>MID_CURRENT_MAX_A || fabsf(iq)>MID_CURRENT_MAX_A);
    if (s->sample_rejected) {
        ++s->current_reject_count;
#if defined(FOC_IDENT_RS_REJECT_COUNT_ONLY)
        /* ABI keeps 8-bit run diagnostics. Saturate rather than wrap a long
         * Rs rejection run to zero; 255 means at least 255, not an exit. */
        if (s->current_reject_run<UINT8_MAX) ++s->current_reject_run;
#else
        ++s->current_reject_run;
#endif
        if (s->current_reject_run>s->max_current_reject_run)
            s->max_current_reject_run=s->current_reject_run;
        if ((s->current_reject_run>=MID_CURRENT_REJECT_RUN_LIMIT
#if defined(FOC_IDENT_RS_REJECT_COUNT_ONLY)
             && !MotorIdent_RsAdmission(s)
#endif
            ) ||
            (s->current_reject_count>MID_MAX_CURRENT_REJECTS
#if defined(FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT)
             && !MotorIdent_RsAdmission(s) /* Estimator-only, no lease extension. */
#endif
            )) {
            MotorIdent_End(s,MID_CURRENT);*d=*q=0;return 0;
        }
    } else {s->current_reject_run=0;++s->current_good_count;}
#endif
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
    *d=*q=0; /* No current-controller reference in this exclusive image. */
#else
    float ref=s->mode==MID_RS ? s->current_a : elapsed<MID_STEP_US ? .05f : .10f;
    *d=s->mode==MID_LQ ? 0 : ref;
    *q=s->mode==MID_LQ ? ref : 0;
#endif
    return 1;
}
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
static inline void MotorIdent_Voltage(const MotorIdentification *s,uint32_t now,float *vd,float *vq)
{
    *vd=*vq=0;
    uint32_t elapsed=now-s->start_us;
    if (s->status!=MID_ACTIVE || elapsed<MID_STEP_US || elapsed>=MID_L_DURATION_US) return;
    float v=(float)MID_VOLTAGE_STEP_MV*.001f;
    if (s->mode==MID_LD) *vd=v;
    else if (s->mode==MID_LQ) *vq=v;
}
#endif
static inline uint8_t MotorIdent_Record(MotorIdentification *s,MotorIdentFrame row)
{
    if (s->status!=MID_ACTIVE) return 1;
    if (!isfinite(row.vd) || !isfinite(row.vq) || !isfinite(row.angle))
        MotorIdent_End(s,MID_BAD_DATA);
    else if (row.vd*row.vd+row.vq*row.vq>MID_VOLTAGE_MAX_V*MID_VOLTAGE_MAX_V)
        MotorIdent_End(s,MID_VOLTAGE);
    if (s->status!=MID_ACTIVE) return 0;
    row.us-=s->start_us;
#if defined(FOC_IDENT_CURRENT_REJECT_ENABLE)
    /* Estimator admission only, not a substitute current for the PI. */
    if (s->sample_rejected || fabsf(row.id)>MID_CURRENT_MAX_A || fabsf(row.iq)>MID_CURRENT_MAX_A)
        return 1;
#endif
    uint8_t record=s->mode==MID_RS ?
        (uint8_t)(row.us>=200000U && (!s->count ||
         row.us-s->rows[s->count-1U].us>=6250U)) : (uint8_t)(row.us>=MID_CAPTURE_START_US);
    if (record && s->count<MID_ROWS) {
        row.mode=s->mode;row.status=s->status;row.reason=s->reason;
        s->rows[s->count]=row;++s->count;
    }
    return 1;
}
#endif
