/* Execute the REAL STM32 binding with fake registers. This verifies software
 * writes and ordering, not board wiring, physical timing or hardware trip. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "foc_feedback_binding_stm32.h"
typedef struct { volatile uint32_t CR1, DIER, SR, PSC, ARR, CNT, EGR, BDTR, CCER; } Timer;
typedef struct { volatile uint32_t ODR, BSRR; } Gpio;
typedef struct { volatile uint32_t CFGR, APB1ENR1; } Clock;
static Timer timer1, timer2, timer7;
static Gpio gpio;
static Clock clock_regs;
#define TIM1 (&timer1)
#define TIM2 (&timer2)
#define TIM7 (&timer7)
#define RCC (&clock_regs)
#define DRIVER_SD_GPIO_Port (&gpio)
#define DRIVER_SD_Pin (1U << 6U)
#define TIM7_DAC_IRQn 55U
#define ADC1_2_IRQn 18U
#define TIM_CR1_CEN 1U
#define TIM_CR1_URS 4U
#define TIM_CR1_OPM 8U
#define TIM_SR_UIF 1U
#define TIM_DIER_UIE 1U
#define TIM_EGR_UG 1U
#define TIM_BDTR_MOE (1U << 15U)
#define TIM_BDTR_AOE (1U << 14U)
#define RCC_CFGR_PPRE1 4U
#define RCC_APB1ENR1_TIM2EN 1U
#define RCC_APB1ENR1_TIM7EN 32U
#define ADC_FULL_SCALE 4095U
#define ADC_VREF_MV 4095U
#define CURRENT_GAIN_MV_PER_A 100U
#define FOC_CURRENT_TRIP_A 4.0f
static uint32_t primask, pending, enabled, adc_priority, guard_priority;
static uint32_t ug_ticks, ug_delay, ug_missing;
static uint8_t adc_fault, foc_fault, foc_enable, analog_safe_latched;
static uint8_t encoder_valid, isolated_running, isolated_zero_ready, run_zero_cal_done;
static uint8_t isolated_zero_shutdown_pending;
static uint32_t injected_seq_count, foc_fault_reason, isolated_end_ms;
static uint16_t iu_zero_raw, iv_zero_raw;
static float foc_id_ref_A, foc_iq_ref_A, encoder_theta_e_pred;
static uint32_t __get_PRIMASK(void) { return primask; }
static void __disable_irq(void) { primask=1U; }
static void __set_PRIMASK(uint32_t value) { primask=value; }
static void __DMB(void) { }
static void __DSB(void)
{
    if (gpio.BSRR) { gpio.ODR &= ~(gpio.BSRR >> 16U); gpio.BSRR=0U; }
    if (timer7.EGR) { timer7.EGR=0U; ug_ticks=0U; }
}
static void __NOP(void)
{ if (++ug_ticks>=ug_delay && !ug_missing) { timer7.SR |= TIM_SR_UIF; pending=1U; } }
static void NVIC_DisableIRQ(unsigned irq) { assert(irq==55U); enabled=0U; }
static void NVIC_EnableIRQ(unsigned irq) { assert(irq==55U); enabled=1U; }
static uint32_t NVIC_GetEnableIRQ(unsigned irq) { assert(irq==55U); return enabled; }
static uint32_t NVIC_GetPriority(unsigned irq)
{ if (irq==55U) return guard_priority; assert(irq==18U); return adc_priority; }
static void NVIC_ClearPendingIRQ(unsigned irq) { assert(irq==55U); pending=0U; }
static void HAL_NVIC_SetPriority(unsigned irq,unsigned priority,unsigned sub)
{ assert(!sub); if (irq==55U) guard_priority=priority; else { assert(irq==18U); adc_priority=priority; } }
static uint32_t HAL_RCC_GetPCLK1Freq(void) { return 85000000U; }
#define __HAL_RCC_TIM7_CLK_ENABLE() (clock_regs.APB1ENR1 |= RCC_APB1ENR1_TIM7EN)
static uint32_t AS5047P_DmaNowUs(void) { return timer2.CNT; }
static uint32_t HAL_GetTick(void) { return timer2.CNT/1000U; }
static int IsolatedBench_Locked(void)
{ return analog_safe_latched && !foc_enable && !gpio.ODR &&
    !(timer1.BDTR & (TIM_BDTR_MOE | TIM_BDTR_AOE)) && !timer1.CCER; }
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
static uint8_t lease_expired;
static int ControlChain_DeadlineReached(uint32_t now_us)
{ (void)now_us; return lease_expired; }
#endif
#include "foc_feedback_binding_stm32.inc"

static void reset(void)
{
    timer1=(Timer){0}; timer2=(Timer){.CR1=1U,.PSC=169U,.ARR=UINT32_MAX};
    timer7=(Timer){0}; gpio=(Gpio){0}; clock_regs=(Clock){.CFGR=4U,.APB1ENR1=1U};
    primask=pending=enabled=ug_missing=0U; ug_delay=8U;
    adc_fault=foc_fault=foc_enable=0U; analog_safe_latched=encoder_valid=1U;
    isolated_running=isolated_zero_ready=run_zero_cal_done=1U;
    isolated_zero_shutdown_pending=0U; injected_seq_count=foc_fault_reason=0U;
    iu_zero_raw=iv_zero_raw=1600U; encoder_theta_e_pred=0.0f;
    foc_feedback_safety=(FocFeedbackSafety){0};
    foc_feedback_armed=foc_feedback_zero_ready=0U;
    foc_feedback_control_frame=(FocFeedbackFrame){0};
    foc_feedback_fault=(FocFeedbackFault){0};
    foc_feedback_test_used=0U; foc_feedback_test_us=0U;
}
static void start(int calibrated)
{
    assert(FocFeedbackBinding_Arm(1600U)); timer1.CR1=TIM_CR1_CEN;
    if (calibrated) FocFeedbackBinding_ZeroReady();
    assert(enabled && !pending && guard_priority==0U && adc_priority==1U);
}
static int sample(uint32_t seq,uint32_t us,uint16_t u,uint16_t v)
{
    timer2.CNT=us; injected_seq_count=seq; encoder_theta_e_pred=(float)seq;
    if (!FocFeedbackBinding_PhysicalSeen(u,v)) return 0;
    return FocFeedbackBinding_Control(u,v);
}
static void irq(uint32_t us) { timer2.CNT=us; timer7.SR=TIM_SR_UIF; TIM7_DAC_IRQHandler(); }
static void off(void)
{
    assert(!gpio.ODR && !timer1.CCER && !(timer1.BDTR&(TIM_BDTR_MOE|TIM_BDTR_AOE)));
    assert(!(timer1.CR1&TIM_CR1_CEN) && !timer7.CR1 && !timer7.DIER && !enabled);
    assert(!foc_enable && !isolated_running && adc_fault && foc_fault && analog_safe_latched);
    assert(!foc_feedback_control_frame.ready && !foc_feedback_safety.frame.ready);
    assert(isolated_zero_shutdown_pending && primask==0U);
}
static void shutdown(void)
{
    reset(); start(1);
    /* Deliberately emulate lost output locks, then fault independently of ADC. */
    gpio.ODR=DRIVER_SD_Pin; timer1.BDTR=TIM_BDTR_MOE|TIM_BDTR_AOE;
    timer1.CCER=0x555U; foc_enable=1U;
    FocFeedbackBinding_EmergencyOff(FOC_FP_HW_TRIP); off();
    assert(foc_feedback_safety.protection.reason==FOC_FP_HARDWARE);
    FocFeedbackBinding_EmergencyOff(FOC_FB_CORE_FAULT);
    assert(foc_feedback_safety.protection.reason==FOC_FP_HARDWARE);
    assert(foc_feedback_safety.protection.fault_flags==(FOC_FP_HW_TRIP|FOC_FB_CORE_FAULT));
    assert(!FocFeedbackBinding_Arm(1600U));
    FocFeedbackBinding_ZeroReady(); assert(!foc_feedback_zero_ready);
}
static void no_callbacks(void)
{
    for (int calibrated=0;calibrated<=1;++calibrated) {
        reset(); start(calibrated);
        for (uint32_t us=25U;us<=100U;us+=25U) { irq(us); assert(!foc_fault); }
        irq(125U); off(); assert(foc_feedback_safety.protection.reason==FOC_FP_TIMEOUT);
        assert(foc_feedback_guard_irqs==5U);
    }
    reset(); start(1);
    for (uint32_t n=1U;n<=4U;++n) (void)sample(n,n*50U,1600U,1600U);
    assert(foc_feedback_control_frame.ready);
    irq(301U); off(); assert(foc_feedback_safety.protection.reason==FOC_FP_TIMEOUT);
}
static void real_pipeline(void)
{
    reset(); start(1);
    for (uint32_t n=1U;n<=100U;++n) {
        assert(sample(n,n*50U,1600U,1600U)==(n>=4U));
        irq(n*50U+25U); assert(!foc_fault);
        if (n>=4U) {
            assert(foc_feedback_control_frame.source_seq==n-1U);
            assert(foc_feedback_control_frame.source_us==(n-1U)*50U);
            assert(foc_feedback_control_frame.measurement_angle==(float)(n-1U));
        }
    }
    char line[320]; FocFeedbackBinding_Format(line,sizeof(line));
    assert(strstr(line,"MOTOR_QUALIFIED=0") && strstr(line,"IRQ=100"));
    assert(strstr(line,"FEEDBACK_N=97"));
    assert(strstr(line,"REPAIR_MAX=6") && strstr(line,"STREAK_MAX=4"));
    assert(foc_feedback_safety.cfg.protection.sample_deadline_us==100U);
    assert(foc_feedback_safety.cfg.protection.confirm_deadline_us==100U);
    assert(foc_feedback_safety.cfg.protection.soft_A==4.0f);
    FocFeedbackBinding_Disarm(); assert(!enabled && !foc_fault);
    reset(); start(1);
    (void)sample(1U,50U,1600U,1600U); (void)sample(2U,100U,1600U,1600U);
    (void)sample(3U,150U,0U,1600U); assert(sample(4U,200U,1600U,1600U));
    assert(!foc_fault && foc_feedback_control_frame.repaired_mask==1U);
    assert(foc_feedback_control_frame.iu_A==0.0f);
    reset(); start(1);
    for (uint32_t n=1U;n<=4U;++n) (void)sample(n,n*50U,1600U,1600U);
    assert(sample(5U,250U,1100U,1600U));
    assert(sample(6U,300U,1100U,1600U));
    assert(foc_feedback_safety.protection.result==FOC_OC_PENDING);
    assert(!sample(7U,350U,1100U,1600U)); off();
    assert(foc_feedback_safety.protection.reason==FOC_FP_CONFIRMED_CURRENT);
}
static void malformed_stream(void)
{
    reset(); start(1); assert(!sample(2U,50U,1600U,1600U)); off();
    assert(foc_feedback_safety.protection.reason==FOC_FP_SEQUENCE);
    reset(); start(1); assert(!sample(1U,50U,4096U,1600U)); off();
    assert(foc_feedback_safety.protection.reason==FOC_FP_RAW_INVALID);
    reset(); start(1); encoder_valid=0U; irq(25U); off();
    assert(foc_feedback_safety.protection.fault_flags & FOC_FB_ENCODER_INVALID);
    reset(); start(1); timer2.CR1=0U; irq(25U); off();
    assert(foc_feedback_safety.protection.fault_flags & FOC_FB_TIMER_INVALID);
    reset(); start(1); irq(0U); off(); /* CNT frozen despite CEN/config looking valid. */
    assert(foc_feedback_safety.protection.fault_flags & FOC_FB_TIMER_INVALID);
    reset(); start(1); timer7.ARR=99U; irq(25U); off();
    reset(); start(1); clock_regs.APB1ENR1 &= ~RCC_APB1ENR1_TIM2EN; irq(25U); off();
    reset(); start(1); adc_priority=0U; irq(25U); off();
    reset(); start(1); gpio.ODR=DRIVER_SD_Pin; irq(25U); off();
    assert(foc_feedback_safety.protection.fault_flags & FOC_FB_OUTPUT_LOCK_LOST);
}
static void timer_setup(void)
{
    for (uint32_t delay=1U;delay<=40U;++delay) {
        reset(); ug_delay=delay; pending=enabled=1U; start(0);
        assert(ug_ticks==delay && !pending && timer7.PSC==169U && timer7.ARR==24U);
        assert(!(timer7.CR1&TIM_CR1_OPM));
    }
    reset(); ug_missing=1U; assert(!FocFeedbackBinding_Arm(1600U)); off();
    assert(ug_ticks==1024U);
    reset(); timer2.PSC=84U; assert(!FocFeedbackBinding_Arm(1600U)); off();
    reset(); assert(!FocFeedbackGuard_Prepare(0U));
    assert(!FocFeedbackGuard_Prepare(170000001U)); assert(!enabled && !timer7.CR1);
}
static void wrap_and_quality(void)
{
    reset(); timer2.CNT=UINT32_MAX-75U; injected_seq_count=UINT32_MAX-2U; start(1);
    uint32_t base=timer2.CNT;
    for (uint32_t n=1U;n<=8U;++n) {
        assert(sample(UINT32_MAX-2U+n,base+n*50U,1600U,1600U)==(n>=4U));
        irq(base+n*50U+25U); assert(!foc_fault);
    }
    reset(); start(1);
    for (uint32_t n=1U;n<=21U;++n) {
        (void)sample(n,n*50U,n%3U==0U?1000U:1600U,1600U);
        assert(!foc_fault);
    }
    assert(foc_feedback_safety.protection.repaired_pairs==6U);
    assert(!sample(22U,1100U,1600U,1600U));
    off(); assert(foc_feedback_safety.protection.reason==FOC_FP_REPAIR_BUDGET);
    assert(foc_feedback_safety.protection.repaired_pairs==7U);
}
static void timing_and_first_fault(void)
{
    reset(); start(1);
    (void)sample(1U,50U,1600U,1600U);
    timer2.CNT=60U; FocFeedbackBinding_WorkEnd(50U);
    assert(foc_feedback_work_n==1U && foc_feedback_work_max_us==10U && !foc_fault);
    timer2.CNT=99U; FocFeedbackBinding_WorkEnd(50U);
    assert(foc_feedback_work_max_us==49U && !foc_fault);
    timer2.CNT=100U; FocFeedbackBinding_WorkEnd(50U); off();
    assert(foc_feedback_work_late==1U && foc_feedback_work_max_us==50U);
    assert(foc_feedback_fault.valid && foc_feedback_fault.off_us==100U);
    assert(foc_feedback_fault.flags & FOC_FB_COMPUTE_LATE);
    assert(foc_feedback_fault.seq==1U && foc_feedback_fault.u==1600U);
    assert(!foc_feedback_fault.sd && !foc_feedback_fault.ccer);
    FocFeedbackFault first=foc_feedback_fault;
    timer2.CNT=1000U; FocFeedbackBinding_EmergencyOff(FOC_FB_CORE_FAULT);
    assert(memcmp(&first,&foc_feedback_fault,sizeof(first))==0);
    char line[320]; FocFeedbackBinding_TimingFormat(line,sizeof(line));
    assert(strstr(line,"MAX_US=50") && strstr(line,"LATE=1"));
    FocFeedbackBinding_FaultFormat(line,sizeof(line));
    assert(strstr(line,"OFF_US=100") && strstr(line,"VALID=1"));
    reset(); start(1); timer2.CNT=5U;
    FocFeedbackBinding_WorkEnd(UINT32_MAX-4U);
    assert(foc_feedback_work_last_us==10U && !foc_fault);
    reset(); start(1); assert(!sample(1U,50U,4096U,1400U)); off();
    assert(foc_feedback_fault.u==4096U && foc_feedback_fault.v==1400U);
    assert(foc_feedback_fault.reason==FOC_FP_RAW_INVALID);
}
static void injected_stopped_stream(void)
{
    reset(); assert(!FocFeedbackBinding_TestTimeout());
    start(0); assert(!FocFeedbackBinding_TestTimeout());
    FocFeedbackBinding_ZeroReady();
    for (uint32_t n=1U;n<=4U;++n) (void)sample(n,n*50U,1600U,1600U);
    timer2.CNT=225U; assert(FocFeedbackBinding_TestTimeout());
    assert(!(timer1.CR1&TIM_CR1_CEN) && enabled && foc_feedback_armed);
    assert(foc_feedback_test_used && foc_feedback_test_us==225U);
    assert(!FocFeedbackBinding_TestTimeout());
    /* At most one already-triggered pair may still complete after trigger stop. */
    (void)sample(5U,250U,1600U,1600U);
    irq(350U); assert(!foc_fault);
    irq(375U); off(); assert(foc_feedback_fault.reason==FOC_FP_TIMEOUT);
    assert(foc_feedback_fault.last_valid_us==250U && foc_feedback_fault.off_us==375U);
    reset(); start(1); gpio.ODR=DRIVER_SD_Pin;
    assert(!FocFeedbackBinding_TestTimeout());
    assert(!foc_feedback_test_used); /* Not admitted on an unlocked fixture. */
}
int main(int argc,char **argv)
{
    assert(argc==2);
    switch (atoi(argv[1])) {
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
    case 8:
        reset(); start(1);
        (void)sample(1U,50U,1600U,1600U);
        lease_expired=1U; irq(75U); off();
        assert(foc_feedback_fault.flags & FOC_FB_CONTROL_LEASE_EXPIRED);
        assert(foc_feedback_fault.reason==FOC_FP_HEALTH);
        break;
#endif
    case 0: shutdown(); break; case 1: no_callbacks(); break; case 2: real_pipeline(); break;
    case 3: malformed_stream(); break; case 4: timer_setup(); break; case 5: wrap_and_quality(); break;
    case 6: timing_and_first_fault(); break; case 7: injected_stopped_stream(); break;
    default: return 2;
    }
    return 0;
}
