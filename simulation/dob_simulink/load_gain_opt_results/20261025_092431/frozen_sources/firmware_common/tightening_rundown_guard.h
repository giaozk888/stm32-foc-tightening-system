#ifndef TIGHTENING_RUNDOWN_GUARD_H
#define TIGHTENING_RUNDOWN_GUARD_H
#include <stdint.h>
#include <math.h>

/* Application admission only; none of these are PI/current/protection limits.
 * At 20 rpm require >=10 rpm in BOTH existing speed estimators for 100 ms,
 * with >=3 degrees net forward travel in that SAME interval. No travel-only
 * shortcut: a lone encoder glitch must not arm contact. */
#define RUNDOWN_ARM_SPEED_RPM       10.0f
#define RUNDOWN_ARM_SPEED_RATIO      0.50f
#define RUNDOWN_ARM_CONFIRM_MS      100U
#define RUNDOWN_ARM_MIN_TRAVEL_DEG    3.0f
#define RUNDOWN_START_TIMEOUT_MS   1500U
#define RUNDOWN_START_DRIVE_IQ_A     0.30f
#define RUNDOWN_START_DRIVE_MS      250U
#define RUNDOWN_ARM_MAX_GAP_MS       30U
enum { RUNDOWN_NOT_ESTABLISHED, RUNDOWN_ARMED };
typedef struct {
    uint32_t last_ms, motion_ms, drive_ms;
    float motion_position;
    uint8_t state, motion_candidate, drive_candidate;
} TightenRundownGuard;
static inline void TightenRundown_Begin(TightenRundownGuard *s)
{ *s=(TightenRundownGuard){0}; }
/* elapsed is actual time since RUNDOWN entry, not a per-call tick counter.
 * Returns failure only; caller owns power-off and the existing outcome path. */
static inline int TightenRundown_Update(TightenRundownGuard *s,
    uint32_t elapsed,float command,float ctrl,float detect,float position,
    float iqref,uint8_t encoder_ok)
{
    if (s->state==RUNDOWN_ARMED) return 0;
    if ((uint32_t)(elapsed-s->last_ms)>RUNDOWN_ARM_MAX_GAP_MS) {
        s->motion_candidate=0U; s->drive_candidate=0U;
    }
    s->last_ms=elapsed;
    float direction=command<0.0f ? -1.0f : 1.0f;
    float speed=fmaxf(RUNDOWN_ARM_SPEED_RPM,fabsf(command)*RUNDOWN_ARM_SPEED_RATIO);
    int moving=encoder_ok && isfinite(command) && fabsf(command)>0.0f &&
        isfinite(ctrl) && isfinite(detect) && isfinite(position) &&
        direction*ctrl>=speed && direction*detect>=speed;
    if (!moving) s->motion_candidate=0U;
    else if (!s->motion_candidate) {
        s->motion_candidate=1U; s->motion_ms=elapsed; s->motion_position=position;
    } else if ((uint32_t)(elapsed-s->motion_ms)>=RUNDOWN_ARM_CONFIRM_MS &&
               direction*(position-s->motion_position)>=RUNDOWN_ARM_MIN_TRAVEL_DEG) {
        s->state=RUNDOWN_ARMED; return 0;
    }
    if (!isfinite(iqref) || direction*iqref<RUNDOWN_START_DRIVE_IQ_A)
        s->drive_candidate=0U;
    else if (!s->drive_candidate) { s->drive_candidate=1U; s->drive_ms=elapsed; }
    return elapsed>=RUNDOWN_START_TIMEOUT_MS && s->drive_candidate &&
        (uint32_t)(elapsed-s->drive_ms)>=RUNDOWN_START_DRIVE_MS;
}
static inline int TightenRundown_CanContact(const TightenRundownGuard *s)
{ return s->state==RUNDOWN_ARMED; }
static inline int TightenRundown_CanOk(const TightenRundownGuard *s,uint8_t contact)
{ return TightenRundown_CanContact(s) && contact; }
#endif
