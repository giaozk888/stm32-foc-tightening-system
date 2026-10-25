#ifndef PROTECTED_READINESS_H
#define PROTECTED_READINESS_H
#include <stdint.h>

/* Task-only admission evidence. The first failed predicate is retained: the
 * existing && short circuit is intentional, not a coherent whole-system scan. */
enum {
    CL_READY_STATE=1U<<0, CL_READY_USED=1U<<1, CL_READY_ARMED=1U<<2,
    CL_READY_REQUEST=1U<<3, CL_READY_ADC_FAULT=1U<<4, CL_READY_FOC_FAULT=1U<<5,
    CL_READY_ZERO=1U<<6, CL_READY_UPDATE=1U<<7, CL_READY_BOOT=1U<<8,
    CL_READY_UART=1U<<9, CL_READY_PWM=1U<<10, CL_READY_WORK=1U<<11,
    CL_READY_OUTER=1U<<12, CL_READY_PERIODIC=1U<<13, CL_READY_CURRENT=1U<<14,
    CL_READY_TIMER=1U<<15, CL_READY_GATES=1U<<16, CL_READY_ADC_AGE=1U<<17,
    CL_READY_ENCODER=1U<<18, CL_READY_SPEED=1U<<19, CL_READY_MODE=1U<<20,
    CL_READY_BUSY=1U<<21, CL_READY_START=1U<<22, CL_READY_STOP=1U<<23,
    CL_READY_FCAL_USED=1U<<24, CL_READY_FRICTION=1U<<25,
    CL_READY_SD=1U<<26, CL_READY_MOE=1U<<27, CL_READY_CCER=1U<<28
};
typedef struct {
    uint32_t failed, now_us, adc_us, age_us, clock_valid;
} ProtectedReadiness;
typedef struct {
    ProtectedReadiness check;
    int32_t rpm;
    uint32_t attempt, valid;
} ProtectedReadinessReject;
static inline uint8_t ProtectedReady_Require(ProtectedReadiness *s,int ok,uint32_t reason)
{
    if (!ok) s->failed|=reason;
    return (uint8_t)(ok!=0);
}
#endif
