#ifndef PROTECTED_CLOSED_LOOP_H
#define PROTECTED_CLOSED_LOOP_H
#include <stdint.h>
#if !defined(FOC_PROTECTED_CLOSED_LOOP) || FOC_PROTECTED_CLOSED_LOOP != 1 || \
    !defined(FOC_CURRENT_TREND4) || FOC_CURRENT_TREND4 != 1 || \
    !defined(FOC_CURRENT_SPIKE_ONLY) || FOC_CURRENT_SPIKE_ONLY != 1 || \
    !defined(AS5047P_SPI_DMA) || AS5047P_SPI_DMA != 1 || \
    !defined(FOC_ADC_WINDOW) || FOC_ADC_WINDOW != 1 || \
    !defined(FOC_ADC_SENSE_TOPOLOGY) || FOC_ADC_SENSE_TOPOLOGY != 2 || \
    defined(FOC_ISOLATED_CONCURRENCY) || defined(FOC_FEEDBACK_SAFETY_BINDING) || \
    defined(FOC_CONTROL_CHAIN_RECONNECT) || defined(FOC_RAW_OBSERVE_ONLY) || \
    defined(FOC_FILTERED_OBSERVE_ONLY) || defined(ZERO_RETEST_BOOT) || \
    defined(SWITCH_FEEDBACK_DIAGNOSTIC) || defined(SAFETY_LOCKED_BOOT)
#error Protected motor trial requires its separate low-side profile, no diagnostic bypasses
#endif
enum { CL_CALIBRATING, CL_READY, CL_RUNNING, CL_DONE, CL_FAULT };
enum { CL_BAD_ADC=4U, CL_BAD_ZERO=8U, CL_BAD_OUTPUT=16U, CL_BAD_ENCODER=32U,
       CL_CORE_FAULT=64U, CL_BAD_TIMER=128U, CL_COMPUTE_LATE=256U,
       CL_OUTER_STALE=512U, CL_OVERSPEED=1024U, CL_BAD_ADMISSION=2048U };
/* The loaded-FSM trial keeps the same 20 rpm admission and all protection
 * thresholds. Only its one-shot session lease covers the existing 8 s
 * rundown + 2 s stop settle + 1.7 s current/hold sequence. */
#if defined(FOC_LOADED_FSM_TRIAL)
#if !defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
#error Loaded FSM trial requires the protected original-FSM pipeline
#endif
#define CL_LEASE_TEXT "12000000"
enum { CL_MAX_US=12000000U };
#else
#define CL_LEASE_TEXT "400000"
enum { CL_MAX_US=400000U };
#endif
enum { CL_OUTER_DEADLINE_US=2000U, CL_SPEED_RPM=20U,
       CL_OVERSPEED_RPM=60U, CL_REPAIR_WINDOW=6U, CL_REPAIR_STREAK=4U };
/* One admission per boot; STOP consumes a queued request too. No reset/clear
 * function is exposed. Time arithmetic works across a 32-bit clock wrap. */
typedef struct {
    uint32_t start_us, outer_us;
    uint8_t state, used, queued, started;
} ClSession;
static inline int ClSession_Queue(ClSession *s, uint8_t healthy)
{
    if (!healthy || s->state!=CL_READY || s->used || s->queued) return 0;
    s->used=1U; s->queued=1U; return 1;
}
static inline int ClSession_Start(ClSession *s, uint32_t now, uint8_t healthy)
{
    if (!s->queued || !healthy || s->state!=CL_READY) {
        s->queued=0U; return 0;
    }
    s->queued=0U; s->started=1U; s->start_us=s->outer_us=now; s->state=CL_RUNNING; return 1;
}
static inline void ClSession_Stop(ClSession *s)
{
    s->queued=0U;
    if (s->state!=CL_FAULT) s->state=CL_DONE;
}
static inline void ClSession_Trip(ClSession *s)
{ s->queued=0U; s->state=CL_FAULT; }
static inline int ClSession_Expired(const ClSession *s, uint32_t now)
{ return s->state==CL_RUNNING && (uint32_t)(now-s->start_us)>=CL_MAX_US; }
void ProtectedLoop_EmergencyOff(uint32_t flags);
void ProtectedLoop_AdcIrq(void);
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
void ProtectedLoop_PwmEntry(void);
void ProtectedLoop_PwmInvalidate(void);
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
/* Commit transaction only: 0 denied, 1 gates OFF, 2 admitted RUNNING gates ON.
 * This predicate never enables or restores an output. */
unsigned ProtectedLoop_PwmCommitPermit(void);
#endif
#endif
#if defined(FOC_FAST_CURRENT_REJECT)
void ProtectedLoop_AdcProfileEnd(uint32_t start);
#endif
#endif
