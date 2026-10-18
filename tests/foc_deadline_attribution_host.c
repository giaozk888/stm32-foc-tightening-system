#include "main.h"
#include "foc_preempt_probe.h"
#include "foc_pwm_write_probe.h"
#include <assert.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
/* A failed assertion must return evidence, not open a Windows CRT dialog. */
#undef assert
#define assert(condition) do { if (!(condition)) { \
    fprintf(stderr,"CHECK failed line %d: %s\n",__LINE__,#condition); exit(1); } } while (0)
DWT_Type mock_dwt;
TIM_TypeDef mock_tim;
uint32_t mock_primask,mock_ipsr,mock_priority[104],mock_enabled[104],mock_group=3U;
FocPwmWriteProbe foc_pwm_write_profile,foc_pwm_duty_profile;
uint32_t foc_ccr_probe_blocked,foc_ccr_probe_hard_late,foc_ccr_probe_latch_late;
uint32_t foc_ccr_probe_post_unsafe,foc_pending_commit_max_cycles,foc_pending_generation_max_cycles;
int32_t foc_ccr_probe_latch_margin_min;
static int inject=-1, inject_source;
static unsigned assisted, publish_observed;
static char output[8192];
void mock_capture_point(unsigned point)
{
    if ((int)point!=inject) return;
    inject=-1; ++assisted;
    uint32_t now=mock_dwt.CYCCNT;
    FocPreToken t=FocPreempt_IrqBegin((unsigned)inject_source);
    mock_dwt.CYCCNT=now+400U;
    FocPreempt_IrqEnd((unsigned)inject_source,t);
}
void mock_barrier(void)
{
    if (deadline_snapshot.valid) {
        assert(deadline_snapshot.wall_cycles==deadline_snapshot.active_est_cycles+
            deadline_snapshot.preempt_total_cycles);
        assert(deadline_snapshot.preempt_total_cycles==deadline_snapshot.tim2_cycles+
            deadline_snapshot.dma_rx_cycles+deadline_snapshot.other_irq_cycles);
        assert(deadline_snapshot.dwt_exit-deadline_snapshot.dwt_entry==
            deadline_snapshot.wall_cycles);
        ++publish_observed;
    }
}
size_t UART_Async_Printf(size_t size,uint32_t timeout,const char *format,...)
{
    (void)size; assert(!mock_ipsr && !mock_primask && !timeout);
    va_list ap; va_start(ap,format);
    size_t n=strlen(output);
    int added=vsnprintf(output+n,sizeof(output)-n,format,ap);
    va_end(ap); assert(added>0 && n+(size_t)added<sizeof(output));
    return (size_t)added;
}
static void setup(void)
{
    for (unsigned i=0;i<104U;++i) mock_priority[i]=15U;
    mock_priority[TIM7_DAC_IRQn+2]=3U;
    mock_priority[ADC1_2_IRQn+2]=2U;
    mock_priority[TIM2_IRQn+2]=mock_priority[DMA1_Channel4_IRQn+2]=
        mock_priority[DMA1_Channel5_IRQn+2]=1U;
    FocPreempt_CheckPriorities(); assert(foc_probe_priorities_ok);
    mock_tim.CNT=1234U; mock_tim.CR1=TIM_CR1_DIR;
    mock_ipsr=34U;
}
static void irq(unsigned source,uint32_t start,uint32_t end)
{
    mock_dwt.CYCCNT=start; FocPreToken t=FocPreempt_IrqBegin(source);
    mock_dwt.CYCCNT=end; FocPreempt_IrqEnd(source,t);
}
int main(int argc,char **argv)
{
    (void)argv; setup();
#if FOC_HEAVY_PROFILE_ENABLE
    /* Independent reset for each possible IRQ interruption between the DWT,
     * timer, cycle and count reads. No masking or retry in production. */
    for (int edge=0;edge<2;++edge) for (int point=0;point<10;++point)
        for (int source=1;source<4;++source) {
            memset((void *)&deadline_snapshot,0,sizeof(deadline_snapshot));
            memset((void *)&foc_preempt_timing,0,sizeof(foc_preempt_timing));
            memset((void *)foc_preempt_irq,0,sizeof(foc_preempt_irq));
            inject_source=source; inject=edge==0 ? point : -1;
            mock_dwt.CYCCNT=100U; uint32_t start=FocPreempt_Begin();
            irq(FOC_PRE_TIMER,1000U,2200U);
            irq(FOC_PRE_RX,3000U,3600U);
            inject=edge==1 ? point : -1;
            mock_dwt.CYCCNT=9000U;
            assert(FocPreempt_End(start,1U)==8900U);
            assert(!mock_primask && !foc_preempt_timing.invalid);
            assert(deadline_snapshot.captured && deadline_snapshot.valid);
            /* Entry-assisted IRQ lies inside the measured frame; exit-assisted
             * IRQ starts exactly at its end and belongs to the observer tail. */
            uint32_t extra=edge==0 && (point<=2 || point>=4) ? 400U : 0U;
            assert(deadline_snapshot.tim2_cycles==1200U+(source==1 ? extra : 0U));
            assert(deadline_snapshot.dma_rx_cycles==600U+(source==2 ? extra : 0U));
            assert(deadline_snapshot.other_irq_cycles==(source==3 ? extra : 0U));
            assert(deadline_snapshot.tim1_cnt==1234U && deadline_snapshot.tim1_dir==1U);
            FocDeadlineSnapshot frozen=deadline_snapshot;
            mock_dwt.CYCCNT=20000U; start=FocPreempt_Begin();
            mock_dwt.CYCCNT=30000U; FocPreempt_End(start,1U);
            assert(!memcmp(&frozen,(const void *)&deadline_snapshot,sizeof(frozen)));
        }
    assert(assisted && foc_stamp_assisted_count==assisted && publish_observed);
    /* Rollover is unsigned subtraction, including cumulative IRQ ledgers. */
    memset((void *)&deadline_snapshot,0,sizeof(deadline_snapshot));
    memset((void *)&foc_preempt_timing,0,sizeof(foc_preempt_timing));
    foc_preempt_irq[1].cycles=UINT32_MAX-500U;
    foc_preempt_irq[1].count=UINT32_MAX;
    mock_dwt.CYCCNT=UINT32_MAX-99U; uint32_t start=FocPreempt_Begin();
    irq(1U,10U,210U);
    mock_dwt.CYCCNT=9000U; FocPreempt_End(start,1U);
    assert(deadline_snapshot.valid && deadline_snapshot.tim2_cycles==200U &&
        deadline_snapshot.tim2_count==1U && deadline_snapshot.wall_cycles==9100U);
    /* Unexpected uninstrumented higher IRQ is NOT falsely declared valid. */
    memset((void *)&deadline_snapshot,0,sizeof(deadline_snapshot));
    memset((void *)&foc_preempt_timing,0,sizeof(foc_preempt_timing));
    mock_enabled[8]=1U; mock_priority[8]=1U; FocPreempt_CheckPriorities();
    mock_dwt.CYCCNT=40000U; start=FocPreempt_Begin();
    mock_dwt.CYCCNT=49000U; FocPreempt_End(start,1U);
    assert(deadline_snapshot.captured && !deadline_snapshot.valid);
#else
    (void)argc; (void)irq;
    mock_dwt.CYCCNT=100U; uint32_t start=FocPreempt_Begin();
    irq(1U,200U,500U);
    mock_dwt.CYCCNT=9000U; assert(FocPreempt_End(start,1U)==8900U);
    assert(foc_preempt_timing.wall_max==8900U && foc_preempt_timing.deadline_miss==1U);
    assert(!deadline_snapshot.captured && !foc_preempt_irq[1].count);
    mock_ipsr=0U; FocPreempt_Monitor();
    assert(strstr(output,"wall_max_us=") && strstr(output,"actual_margin_min_us="));
    assert(!strstr(output,"IRQ PREEMPT") && !strstr(output,"HYPOTHETICAL"));
#endif
    (void)argc;
    puts("PASS coherent first deadline / assisted read races / rollover / frozen publication / heavy switch");
}
