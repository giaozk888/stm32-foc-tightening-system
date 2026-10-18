/* Execute the production fast entry with W1C semantics and synthetic events.
 * Not a physical ADC synchrony or timing measurement. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "foc_hot_path.h"
#include "foc_fast_path_profile.h"
#define ADC_IT_JEOC (1U<<5)
#define ADC_IT_JEOS (1U<<6)
#define ADC_FLAG_JEOC ADC_IT_JEOC
#define ADC_FLAG_JEOS ADC_IT_JEOS
#define AWD (1U<<7)
#define OVR (1U<<4)
#define JQOVF (1U<<10)
#define CL_BAD_ADC 4U
#define HAL_ADC_STATE_INJ_EOC 0x400U
#define SET_BIT(reg,bits) ((reg)|=(bits))
typedef struct { uint32_t ISR,IER,JDR1; } Adc;
typedef struct { Adc *Instance; uint32_t State; } ADC_HandleTypeDef;
static Adc a1,a2;
static ADC_HandleTypeDef hadc1={&a1,0U},hadc2={&a2,0U};
static uint32_t mask,reads,acks,seq_calls,math_calls,hal_calls,ended,injected_seq_count,current_valid_count;
static uint32_t pair_misses,recorded,power,fault,event_during_math;
static uint8_t adc_fault;
static uint8_t pair_returns_zero;
static uint16_t iu_inj_raw,iv_inj_raw;
#if defined(FOC_FAST_CURRENT_REJECT)
#include "foc_feedback_safety_candidate.h"
#include "foc_guard_integer.h"
static FocFeedbackFrame cl_frame;
static FocFeedbackSafety fast_safety;
static uint8_t cl_current_path,cl_armed=1U;
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
static uint32_t foc_pending_held;
#endif
static float encoder_theta_e_pred,encoder_omega_e_rad_s;
#define FOC_TS_S 0.00005f
#define TWO_PI_F 6.28318530718f
#define CL_BAD_ENCODER 32U
static unsigned pwm_writes;
static float command_d,command_q;
#else
static struct { uint16_t u,v; } cl_frame;
#endif
#if defined(FOC_LATEST_ORIGINAL_FSM)
enum { CL_READY,CL_RUNNING,CL_FAULT };
static struct { unsigned state; } cl_session;
static volatile float foc_int_d_V,foc_int_q_V;
#endif
static uint32_t __get_PRIMASK(void) { return mask; }
#if defined(FOC_FAST_MATH)
#include "foc_irq_load.h"
static struct { uint32_t CYCCNT; } mock_dwt;
#define DWT (&mock_dwt)
static FocIrqLoad irq_load;
static uint32_t cl_cpu_max_cyc,cl_preempt_max_cyc;
static uint32_t cl_pair_max_us,cl_math_max_us;
#if defined(FOC_PAIR_FAST_PATH)
static FocFrameCost cl_frame_cost;
static uint32_t cl_seq=17U;
#endif
uint32_t FocIrqLoad_Read(void) { return FocIrqLoad_Total(&irq_load,DWT->CYCCNT); }
#if defined(FOC_IRQ_SOURCE_TRACE)
static FocIrqSources sources;
static FocIrqSourceFrame cl_frame_irq;
void FocIrqSource_FrameBegin(void) { assert(mask); FocIrqSources_FrameBegin(&sources); }
void FocIrqSource_FrameEnd(FocIrqSourceFrame *out) { FocIrqSources_FrameEnd(&sources,out); }
#endif
#endif
static void __disable_irq(void) { mask=1U; }
static void __set_PRIMASK(uint32_t value) { mask=value; }
static void __DMB(void) { }
static uint32_t AS5047P_DmaNowUs(void) { return 123U; }
static int FocAdcTiming_PairReady(void)
{
    assert(mask); ++reads;
    int ok=(a1.ISR&ADC_IT_JEOS) && (a2.ISR&ADC_IT_JEOS);
    if (!ok) ++pair_misses;
    return ok;
}
static void clear(ADC_HandleTypeDef *h,uint32_t flags)
{ assert(mask && !math_calls); ++acks; h->Instance->ISR&=~flags; }
#define __HAL_ADC_CLEAR_FLAG(h,flags) clear((h),(flags))
#define __HAL_ADC_DISABLE_IT(h,bits) ((h)->Instance->IER&=~(bits))
static void ProtectedLoop_EmergencyOff(uint32_t flags) {
    power=0U; fault|=flags;
#if defined(FOC_FAST_CURRENT_REJECT)
    cl_armed=0U;
#endif
}
#if defined(FOC_FAST_CURRENT_REJECT)
static void ProtectedLoop_AdvanceAngle(void) {
    encoder_theta_e_pred+=encoder_omega_e_rad_s*FOC_TS_S;
}
#endif
static void HAL_ADC_IRQHandler(ADC_HandleTypeDef *h)
{
    assert(!power && fault && !(h->Instance->IER&(ADC_IT_JEOC|ADC_IT_JEOS)));
    ++hal_calls; h->Instance->ISR&=~(AWD|OVR|JQOVF);
}
static void FocAdcTiming_RecordRaw(uint16_t u,uint16_t v)
{
    assert(!mask && acks==2U && !(a1.ISR&ADC_IT_JEOS) && !(a2.ISR&ADC_IT_JEOS));
    assert(u==1111U && v==2222U); ++recorded;
}
static int ProtectedLoop_Pair(uint16_t u,uint16_t v)
{ assert(!mask && recorded==1U && injected_seq_count==1U); ++seq_calls;
#if defined(FOC_FAST_CURRENT_REJECT)
  FocOcConfirmResult r=FocFeedbackSafety_Push(&fast_safety,1U,123U,u,v,encoder_theta_e_pred,0U,1U);
  cl_current_path=fast_safety.validation.last_path;
  if (r==FOC_OC_TRIPPED) ProtectedLoop_EmergencyOff(CL_BAD_ADC);
  return FocFeedbackSafety_Take(&fast_safety,123U,0U,1U,&cl_frame);
#else
  cl_frame.u=u; cl_frame.v=v; return !pair_returns_zero; }
#endif
#if defined(FOC_FAST_CURRENT_REJECT)
}
#endif
static void FOC_CurrentLoopStep(uint16_t u,uint16_t v,uint16_t raw_u,uint16_t raw_v)
{
    assert(!mask && u==raw_u && v==raw_v && acks==2U); ++math_calls;
#if defined(FOC_LATEST_ORIGINAL_FSM)
    /* Integration stub intentionally accumulates PI memory each step. */
    foc_int_d_V+=.125f; foc_int_q_V-=.125f;
#endif
#if defined(FOC_FAST_CURRENT_REJECT)
    command_d+=.25f; command_q-=.25f; ++pwm_writes;
#endif
#if defined(FOC_FAST_MATH)
    DWT->CYCCNT+=170U;
    FocIrqLoad_Begin(&irq_load,DWT->CYCCNT);
#if defined(FOC_IRQ_SOURCE_TRACE)
    FocIrqSources_Enter(&sources,FOC_IRQ_GUARD,DWT->CYCCNT);
#endif
    DWT->CYCCNT+=30U;
    FocIrqLoad_End(&irq_load,DWT->CYCCNT);
#if defined(FOC_IRQ_SOURCE_TRACE)
    FocIrqSources_Leave(&sources,FOC_IRQ_GUARD,DWT->CYCCNT);
#endif
#endif
    if (event_during_math) {
        a1.JDR1=3333U; a2.JDR1=4444U;
        a1.ISR|=ADC_IT_JEOS|ADC_IT_JEOC; a2.ISR|=ADC_IT_JEOS|ADC_IT_JEOC;
    }
}
static void ProtectedLoop_WorkEnd(uint32_t begin) { assert(begin==123U); ++ended; }
#include "protected_adc_irq.inc"
static void reset(void)
{
#if defined(FOC_FAST_MATH)
    mock_dwt.CYCCNT=0U; irq_load=(FocIrqLoad){0};
#if defined(FOC_IRQ_SOURCE_TRACE)
    sources=(FocIrqSources){0}; cl_frame_irq=(FocIrqSourceFrame){0};
#endif
    cl_cpu_max_cyc=cl_preempt_max_cyc=cl_pair_max_us=cl_math_max_us=0U;
#endif
    a1=(Adc){ADC_IT_JEOS|ADC_IT_JEOC,ADC_IT_JEOS,1111U};
    a2=(Adc){ADC_IT_JEOS|ADC_IT_JEOC,0U,2222U};
    hadc1.State=hadc2.State=0U;
    mask=reads=acks=seq_calls=math_calls=hal_calls=ended=injected_seq_count=current_valid_count=0U;
    pair_misses=recorded=fault=event_during_math=adc_fault=0U; power=1U;
    pair_returns_zero=0U;
}
int main(void)
{
    reset(); ProtectedLoop_AdcIrq();
    assert(!mask && reads==1U && acks==2U && recorded==1U && seq_calls==1U &&
           math_calls==1U && ended==1U && current_valid_count==1U && !hal_calls && !fault);
    assert(hadc1.State&HAL_ADC_STATE_INJ_EOC);
#if defined(FOC_IRQ_SOURCE_TRACE)
    assert(!sources.active && !sources.stats.error && cl_frame_irq.cycles[0]==30U && cl_frame_irq.calls[0]==1U);
    reset(); pair_returns_zero=1U; ProtectedLoop_AdcIrq();
    assert(!sources.active && !sources.stats.error && !ended && !math_calls);
    reset(); ProtectedLoop_AdcIrq();
#endif
#if defined(FOC_FAST_MATH)
    assert(cl_cpu_max_cyc==170U && cl_preempt_max_cyc==30U && irq_load.depth==0U);
#if defined(FOC_PAIR_FAST_PATH)
    assert(cl_frame_cost.seq==17U && cl_frame_cost.wall_cyc==200U && cl_frame_cost.irq_cyc==30U);
#endif
#endif
    reset(); event_during_math=1U; ProtectedLoop_AdcIrq();
    assert(a1.ISR&ADC_IT_JEOS); assert(a2.ISR&ADC_IT_JEOS); /* No late W1C! */
    assert(a1.JDR1==3333U && a2.JDR1==4444U && !hal_calls);
    reset(); a2.ISR=0U; ProtectedLoop_AdcIrq();
    assert(pair_misses==1U && !power && adc_fault && fault && !math_calls && !recorded);
    assert(!(a1.IER&ADC_IT_JEOS));
    const uint32_t errors[]={AWD,OVR,JQOVF};
    for (unsigned i=0;i<3U;++i) for (unsigned adc=0;adc<2U;++adc) {
        reset(); Adc *a=adc==0U ? &a1 : &a2;
        a->ISR|=errors[i]; a->IER|=errors[i]; ProtectedLoop_AdcIrq();
        assert(!power && adc_fault && fault && hal_calls==1U && !math_calls && !recorded);
        assert(!(a->ISR&errors[i]) && !(a1.IER&ADC_IT_JEOS) && !mask);
    }
    reset(); a2.IER=ADC_IT_JEOS; ProtectedLoop_AdcIrq();
    assert(fault && !power && !math_calls && !hal_calls && !a2.IER);
    reset(); a1.IER|=ADC_IT_JEOC; ProtectedLoop_AdcIrq();
    assert(fault && !math_calls && !a1.IER);
    reset(); a1.ISR=a2.ISR=0U; ProtectedLoop_AdcIrq();
    assert(!fault && !acks && !math_calls && !recorded && !mask); /* Spurious IRQ. */
    reset(); a1.IER=0U; ProtectedLoop_AdcIrq(); assert(!recorded && !acks);
    puts("PASS early read/ack, new completion retained, missing pair/errors/second owner fail closed");
    return 0;
}
