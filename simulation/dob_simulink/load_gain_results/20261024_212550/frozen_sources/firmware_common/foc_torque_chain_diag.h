#ifndef FOC_TORQUE_CHAIN_DIAG_H
#define FOC_TORQUE_CHAIN_DIAG_H
#include <stdint.h>
#include <string.h>
#if defined(FOC_ANGLE_CHAIN_DIAG)
#include "foc_angle_chain_diag.h"
#endif
#if defined(FOC_BREAKAWAY_CURRENT_TEST) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND) || (defined(FOC_ANGLE_CHAIN_DIAG) && !defined(FOC_ANGLE_HAND_ONLY))
#include "foc_breakaway_current_test.h"
#endif
/* Manual-only, one accepted request per boot. No arbitrary current/offset setter. */
#ifndef FOC_TORQUE_CHAIN_IQ_MA
#define FOC_TORQUE_CHAIN_IQ_MA 100
#endif
#if FOC_TORQUE_CHAIN_IQ_MA == 50
/* Explicit legacy profile only; preserve its pinned 50mA evidence. */
#define FOC_TORQUE_CHAIN_IQ_A 0.05f
#define FOC_TORQUE_CHAIN_IQ_TEXT "50"
#elif FOC_TORQUE_CHAIN_IQ_MA == 100
#define FOC_TORQUE_CHAIN_IQ_A 0.10f
#define FOC_TORQUE_CHAIN_IQ_TEXT "100"
#elif FOC_TORQUE_CHAIN_IQ_MA == 200
/* Explicit manual positive-only comparison; not a production current limit. */
#define FOC_TORQUE_CHAIN_IQ_A 0.20f
#define FOC_TORQUE_CHAIN_IQ_TEXT "200"
#elif FOC_TORQUE_CHAIN_IQ_MA == 350 && (defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_ANGLE_CHAIN_DIAG))
#define FOC_TORQUE_CHAIN_IQ_A 0.35f
#define FOC_TORQUE_CHAIN_IQ_TEXT "350"
#elif FOC_TORQUE_CHAIN_IQ_MA == 450 && defined(FOC_TORQUE450_FIVE_SECOND)
#define FOC_TORQUE_CHAIN_IQ_A 0.45f
#define FOC_TORQUE_CHAIN_IQ_TEXT "450"
#else
#error Torque diagnostic supports only explicit 50mA, 100mA or positive 200mA profiles
#endif
#if defined(FOC_ANGLE_CHAIN_DIAG)
#define FOC_TORQUE_CHAIN_MAX_US ANGLE_OFFSET_LEASE_US
#define FOC_TORQUE_CHAIN_PERIOD_US ANGLE_OFFSET_PERIOD_US
#elif defined(FOC_SPEED_DYNAMIC_DIAG) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND)
#if defined(FOC_BREAKAWAY_CURRENT_TEST)
#error Dynamic speed diagnostic cannot run fixed-current breakaway tests
#endif
#define FOC_TORQUE_CHAIN_MAX_US 5000000U
#define FOC_TORQUE_CHAIN_PERIOD_US 200000U
#elif defined(FOC_BREAKAWAY_CURRENT_TEST)
#define FOC_TORQUE_CHAIN_MAX_US BREAKAWAY_TEST_DURATION_US
#define FOC_TORQUE_CHAIN_PERIOD_US BREAKAWAY_RECORD_PERIOD_US
#else
#define FOC_TORQUE_CHAIN_MAX_US 200000U
#define FOC_TORQUE_CHAIN_PERIOD_US 8000U
#endif
#if defined(FOC_BREAKAWAY_CURRENT_TEST)
_Static_assert(FOC_TORQUE_CHAIN_MAX_US==BREAKAWAY_TEST_DURATION_US,"Breakaway lease drift");
_Static_assert(FOC_TORQUE_CHAIN_PERIOD_US==BREAKAWAY_RECORD_PERIOD_US,"Breakaway trace period drift");
#endif
typedef struct {
    uint32_t encoder_before;
    int32_t sign, offset_deg;
    uint8_t used, queued, prepared, admitting, active, denied;
    uint16_t iq_mA; /* Uses former padding; 0 denotes legacy capture. */
} FocTorqueChainDiag;
_Static_assert(sizeof(FocTorqueChainDiag)==20U,"Torque metadata decoder ABI");
static inline int FocTorqueChain_Parse(const char *cmd,int32_t *sign,int32_t *offset)
{
#if defined(FOC_ANGLE_HAND_ONLY)
    (void)cmd; (void)sign; (void)offset; return 0;
#elif defined(FOC_ANGLE_CHAIN_DIAG)
    return FocAngleOffset_Parse(cmd,sign,offset);
#elif defined(FOC_TORQUE350_FIVE_SECOND)
    if (strcmp(cmd,"MOTOR TEST TORQUE350 CONFIRM")) return 0;
    *sign=1; *offset=0; return 1;
#elif defined(FOC_TORQUE450_FIVE_SECOND)
    if (strcmp(cmd,"MOTOR TEST TORQUE450 CONFIRM")) return 0;
    *sign=1; *offset=0; return 1;
#elif defined(FOC_SPEED_DYNAMIC_DIAG)
    if (strcmp(cmd,"MOTOR TEST SPEED500 CONFIRM")) return 0;
    *sign=1; *offset=0; return 1;
#elif defined(FOC_BREAKAWAY_CURRENT_TEST)
    (void)cmd; (void)sign; (void)offset; return 0; /* No legacy/sweep entry. */
#else
    const char *p="MOTOR TEST TORQUE ";
    if (strncmp(cmd,p,strlen(p))) return 0;
    cmd+=strlen(p);
    if (!strncmp(cmd,"POS ",4U)) *sign=1;
#if FOC_TORQUE_CHAIN_IQ_MA != 200
    else if (!strncmp(cmd,"NEG ",4U)) *sign=-1;
#endif
    else return 0;
    cmd+=4U;
    if (!strcmp(cmd,"ZERO CONFIRM")) *offset=0;
#if FOC_TORQUE_CHAIN_IQ_MA == 50
    /* No angle-offset commands in the fixed 100/200mA diagnostics. */
    else if (!strcmp(cmd,"PLUS5 CONFIRM")) *offset=5;
    else if (!strcmp(cmd,"MINUS5 CONFIRM")) *offset=-5;
#endif
    else return 0;
    return 1;
#endif
}
#if defined(FOC_BREAKAWAY_CURRENT_TEST)
/* -2 is explicitly LIMIT_BLOCKED, never silently clamped or consumed. */
__attribute__((optimize("Os"),unused))
static int FocBreakaway_Queue(FocTorqueChainDiag *s,const char *cmd,uint8_t ready,uint16_t limit_ma)
{
    int32_t sign; uint16_t ma;
    if (!FocBreakaway_Parse(cmd,&sign,&ma)) return 0;
    if (!FocBreakaway_WithinLimit(ma,limit_ma)) return -2;
    if (!ready || s->used) return 0;
    s->sign=sign; s->offset_deg=0; s->iq_mA=ma; s->used=s->queued=1U;
    return 1;
}
#endif
static inline int FocTorqueChain_Queue(FocTorqueChainDiag *s,const char *cmd,uint8_t ready)
{
    int32_t sign,offset;
    if (!ready || s->used || !FocTorqueChain_Parse(cmd,&sign,&offset)) return 0;
    s->sign=sign; s->offset_deg=offset; s->used=1U; s->queued=1U;
#if defined(FOC_SPEED_DYNAMIC_DIAG)
    s->iq_mA=0U; /* Not a fixed-current request. */
#elif FOC_TORQUE_CHAIN_IQ_MA != 50
    s->iq_mA=FOC_TORQUE_CHAIN_IQ_MA;
#endif
    return 1;
}
static inline float FocTorqueChain_Angle(float angle,int32_t offset_deg)
{
    angle+=(float)offset_deg*0.01745329251994329577f;
    if (angle<0.0f) angle+=6.2831853071795864769f;
    if (angle>=6.2831853071795864769f) angle-=6.2831853071795864769f;
    return angle;
}
#endif
