#ifndef FOC_ANGLE_CHAIN_DIAG_H
#define FOC_ANGLE_CHAIN_DIAG_H
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "as5047p_protocol.h"

/* Diagnostic tolerances only; never control or protection thresholds.
 * Observe at the existing accepted 1kHz task, save at 50Hz. READ must drain
 * the small ring before overwrite. Summary spans the entire manual session. */
#define ANGLE_HAND_ROWS 12U
#define ANGLE_HAND_PERIOD_US 20000U
#define ANGLE_HAND_MAX_GAP_US 5000U
#define ANGLE_HAND_ERROR_DEG 2.0f
#define ANGLE_HAND_RETURN_COUNTS 128
#define ANGLE_OFFSET_LEASE_US 400000U
#define ANGLE_OFFSET_PERIOD_US 12000U

typedef struct {
    uint32_t seq,us;
    uint16_t raw,flags;
    int32_t mechanical_counts;
    float mechanical_position_deg,electrical_unwrapped_deg,electrical_wrapped_rad;
} FocAngleHandFrame;
typedef struct {
    FocAngleHandFrame rows[ANGLE_HAND_ROWS];
    uint32_t samples,records,start_us,last_us,last_record_us,errors;
    int32_t mechanical_counts,min_counts,max_counts;
    float electrical_deg,last_electrical,initial_position,max_chain_error,max_position_error;
    uint16_t last_raw;
    uint8_t active,passed,finished,have_sample;
} FocAngleHand;
_Static_assert(sizeof(FocAngleHandFrame)==28U,"Angle hand binary ABI");

static inline int FocAngleOffset_Allowed(int32_t deg)
{ return deg==-30 || deg==-20 || deg==-10 || deg==0 || deg==10 || deg==20 || deg==30; }
static inline int FocAngleOffset_Parse(const char *cmd,int32_t *sign,int32_t *offset)
{
    const char *prefix="MOTOR TEST ANGLE OFFSET ";
    if (strncmp(cmd,prefix,strlen(prefix))) return 0;
    const char *suffix=cmd+strlen(prefix);
    /* Exact literal choices, no arbitrary number, duration, sign or sweep. */
    if (!strcmp(suffix,"-30 CONFIRM")) *offset=-30;
    else if (!strcmp(suffix,"-20 CONFIRM")) *offset=-20;
    else if (!strcmp(suffix,"-10 CONFIRM")) *offset=-10;
    else if (!strcmp(suffix,"0 CONFIRM")) *offset=0;
    else if (!strcmp(suffix,"+10 CONFIRM")) *offset=10;
    else if (!strcmp(suffix,"+20 CONFIRM")) *offset=20;
    else if (!strcmp(suffix,"+30 CONFIRM")) *offset=30;
    else return 0;
    *sign=1; return 1;
}
__attribute__((unused,noinline,optimize("Os")))
static void FocAngleHand_Begin(FocAngleHand *s,uint32_t now)
{
    /* Old rows unreachable by sequence after reset; no large masked memset. */
    s->samples=s->records=s->errors=0U; s->start_us=s->last_us=s->last_record_us=now;
    s->mechanical_counts=s->min_counts=s->max_counts=0;
    s->electrical_deg=s->max_chain_error=s->max_position_error=0.0f;
    s->have_sample=s->passed=s->finished=0U; s->active=1U;
}
__attribute__((unused,noinline,optimize("Os")))
static void FocAngleHand_Observe(FocAngleHand *s,uint32_t now,uint16_t raw,
    float actual_electrical_rad,float actual_mechanical_position,uint8_t off,uint8_t valid)
{
    if (!s->active) return;
    if (!off || !valid || raw>=16384U || !isfinite(actual_electrical_rad) ||
        actual_electrical_rad<0.0f || actual_electrical_rad>=6.283186f ||
        !isfinite(actual_mechanical_position)) { ++s->errors; s->passed=0U; s->active=0U; return; }
    if (s->have_sample) {
        if (now-s->last_us>ANGLE_HAND_MAX_GAP_US) ++s->errors;
        int32_t delta=AS5047P_Delta14(raw,s->last_raw);
        if (delta==-8192) ++s->errors; /* Half-turn alias is not proof. */
        s->mechanical_counts-=delta; /* Existing ENCODER_DIRECTION=-1. */
        float de=actual_electrical_rad-s->last_electrical;
        if (de>3.14159265359f) de-=6.28318530718f;
        if (de< -3.14159265359f) de+=6.28318530718f;
        s->electrical_deg+=de*57.2957795131f;
        float err=fabsf(s->electrical_deg-(float)s->mechanical_counts*(3600.0f/16384.0f));
        if (err>s->max_chain_error) s->max_chain_error=err;
        err=fabsf(actual_mechanical_position-s->initial_position-
            (float)s->mechanical_counts*(360.0f/16384.0f));
        if (err>s->max_position_error) s->max_position_error=err;
    } else { s->initial_position=actual_mechanical_position; s->have_sample=1U; }
    if (s->mechanical_counts>s->max_counts) s->max_counts=s->mechanical_counts;
    if (s->mechanical_counts<s->min_counts) s->min_counts=s->mechanical_counts;
    s->last_us=now; s->last_raw=raw; s->last_electrical=actual_electrical_rad; ++s->samples;
    if (!s->records || now-s->last_record_us>=ANGLE_HAND_PERIOD_US) {
        uint32_t seq=s->records;
        s->rows[seq%ANGLE_HAND_ROWS]=(FocAngleHandFrame){seq,now-s->start_us,raw,0U,
            s->mechanical_counts,actual_mechanical_position-s->initial_position,
            s->electrical_deg,actual_electrical_rad};
        s->last_record_us=now; ++s->records; /* Publish complete row last. */
    }
}
__attribute__((unused,noinline,optimize("Os")))
static int FocAngleHand_End(FocAngleHand *s)
{
    s->active=0U; s->finished=1U;
    /* One full turn and return demonstrates both directions without summing
     * raw jitter into fictitious rotations. This is software-chain evidence,
     * not independent physical pole-count or magnetic-zero calibration. */
    uint8_t turn=(uint8_t)((s->max_counts>=16384 || s->min_counts<=-16384) &&
        s->mechanical_counts>=-ANGLE_HAND_RETURN_COUNTS && s->mechanical_counts<=ANGLE_HAND_RETURN_COUNTS);
    s->passed=(uint8_t)(s->have_sample && turn && !s->errors &&
        s->max_chain_error<=ANGLE_HAND_ERROR_DEG && s->max_position_error<=0.1f);
    return s->passed;
}
#endif
