/* Production IRQ hooks and outer timing recorder; no MCU performance claims. */
#include "main.h"
#include "foc_preempt_probe.h"
#include "foc_pwm_write_probe.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
DWT_Type mock_dwt;
TIM_TypeDef mock_tim;
uint32_t mock_primask,mock_ipsr;
uint32_t mock_priority[104],mock_enabled[104],mock_group=3U;
FocPwmWriteProbe foc_pwm_write_profile,foc_pwm_duty_profile;
uint32_t foc_ccr_probe_blocked,foc_ccr_probe_hard_late,foc_ccr_probe_latch_late;
uint32_t foc_ccr_probe_post_unsafe;
int32_t foc_ccr_probe_latch_margin_min;
static unsigned interrupt_barrier;
static char output[8192];
void mock_barrier(void)
{
    if (interrupt_barrier && --interrupt_barrier==0U) {
        foc_preempt_irq[0].cycles+=10U;
        ++foc_preempt_irq[0].count;
    }
}
size_t UART_Async_Printf(size_t size,uint32_t timeout,const char *format,...)
{
    (void)size; assert(!timeout && !mock_ipsr && !mock_primask);
    va_list ap; va_start(ap,format);
    size_t n=strlen(output);
    int result=vsnprintf(output+n,sizeof(output)-n,format,ap);
    va_end(ap); assert(result>0 && (size_t)result<sizeof(output)-n);
    return (size_t)result;
}
static void priorities(void)
{
    for (unsigned i=0U;i<104U;++i) mock_priority[i]=15U;
    mock_priority[TIM7_DAC_IRQn+2]=0U;
    mock_priority[TIM2_IRQn+2]=mock_priority[DMA1_Channel4_IRQn+2]=
        mock_priority[DMA1_Channel5_IRQn+2]=1U;
    mock_priority[ADC1_2_IRQn+2]=2U;
    mock_enabled[TIM7_DAC_IRQn+2]=mock_enabled[TIM2_IRQn+2]=
        mock_enabled[DMA1_Channel4_IRQn+2]=mock_enabled[DMA1_Channel5_IRQn+2]=1U;
    FocPreempt_CheckPriorities(); assert(foc_probe_priorities_ok);
}
int main(void)
{
    priorities(); mock_ipsr=34U;
    mock_dwt.CYCCNT=100U; uint32_t start=FocPreempt_Begin();
    mock_dwt.CYCCNT=120U; FocPreToken timer=FocPreempt_IrqBegin(1U);
    mock_dwt.CYCCNT=130U; FocPreToken guard=FocPreempt_IrqBegin(0U);
    mock_dwt.CYCCNT=180U; FocPreempt_IrqEnd(0U,guard);
    mock_dwt.CYCCNT=200U; FocPreempt_IrqEnd(1U,timer);
    mock_dwt.CYCCNT=300U; assert(FocPreempt_End(start,1U)==200U);
    assert(foc_preempt_irq[0].cycles==50U && foc_preempt_irq[1].cycles==30U);
    assert(foc_preempt_irq[1].max_single==80U); /* inclusive max is NOT summed */
    assert(foc_preempt_timing.preempt_max==80U && foc_preempt_timing.active_est_max==120U);
    assert(foc_preempt_timing.worst_preempt.count[0]==1U &&
        foc_preempt_timing.worst_preempt.count[1]==1U);
    mock_dwt.CYCCNT=1000U; start=FocPreempt_Begin();
    mock_dwt.CYCCNT=5000U; FocPreToken rx=FocPreempt_IrqBegin(2U);
    mock_dwt.CYCCNT=8000U; FocPreempt_IrqEnd(2U,rx);
    mock_dwt.CYCCNT=11103U; assert(FocPreempt_End(start,1U)==10103U);
    assert(foc_preempt_timing.deadline_miss==1U);
    assert(foc_preempt_timing.first_miss.wall==10103U &&
        foc_preempt_timing.first_miss.preempt==3000U &&
        foc_preempt_timing.first_miss.active_est==7103U &&
        foc_preempt_timing.first_miss.valid &&
        foc_preempt_timing.first_miss.dominant==2U &&
        foc_preempt_timing.first_miss.path==1U);
    mock_dwt.CYCCNT=20000U; start=FocPreempt_Begin();
    mock_dwt.CYCCNT+=12000U; FocPreempt_End(start,1U);
    assert(foc_preempt_timing.first_miss.wall==10103U); /* frozen first miss */
    mock_dwt.CYCCNT=UINT32_MAX-49U; start=FocPreempt_Begin();
    mock_dwt.CYCCNT=50U; assert(FocPreempt_End(start,1U)==100U);
    uint32_t invalid=foc_preempt_timing.invalid;
    interrupt_barrier=1U; start=FocPreempt_Begin();
    mock_dwt.CYCCNT+=100U; FocPreempt_End(start,1U);
    assert(foc_preempt_timing.invalid==invalid+1U && !mock_primask);
    mock_enabled[8]=1U; mock_priority[8]=1U;
    FocPreempt_CheckPriorities(); assert(!foc_probe_priorities_ok && foc_probe_unexpected_irq==7U);
    mock_enabled[8]=0U; priorities();
    mock_ipsr=0U; FocPreempt_Monitor();
    assert(strstr(output,"wall_max_us=") && strstr(output,"IRQ PREEMPT TIM7"));
    assert(strstr(output,"FOC MISS IRQ DMA1_CH4 cycles=3000 count=1"));
    assert(strstr(output,"actual_commit_count=0") && strstr(output,"HYPOTHETICAL PWM"));
    puts("PASS production exclusive IRQ attribution / nested / first miss / wrap / nonmasking stamp / task monitor");
    return 0;
}
