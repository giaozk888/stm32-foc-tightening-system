#define main old_attribution_main_not_run
#include "foc_preempt_attribution_host.c"
#undef main
#include <stdlib.h>
#undef assert
#define assert(c) do { if (!(c)) { fprintf(stderr,"line %d: %s\n",__LINE__,#c); exit(1); } } while (0)
uint32_t foc_pending_commit_max_cycles,foc_pending_generation_max_cycles;
int main(void)
{
    for (unsigned i=0;i<104U;++i) mock_priority[i]=15U;
    mock_priority[TIM7_DAC_IRQn+2]=3U;
    mock_priority[TIM2_IRQn+2]=mock_priority[DMA1_Channel4_IRQn+2]=
        mock_priority[DMA1_Channel5_IRQn+2]=3U;
    mock_priority[TIM6_DAC_IRQn+2]=4U;
    mock_priority[ADC1_2_IRQn+2]=2U;
    for (unsigned i=0;i<4U;++i) {
        const int ids[]={TIM7_DAC_IRQn,TIM2_IRQn,DMA1_Channel4_IRQn,DMA1_Channel5_IRQn};
        mock_enabled[ids[i]+2]=1U;
    }
    FocPreempt_CheckPriorities(); assert(foc_probe_priorities_ok);
    /* ADC preempts a lower IRQ during its half-published ledger. These values
     * MUST NOT be mistaken for preemption of ADC (negative/double-counted CPU). */
    for (unsigned source=0U;source<4U;++source) {
        mock_dwt.CYCCNT=100U; FocPreToken lower=FocPreempt_IrqBegin(source);
        foc_preempt_irq[source].cycles=UINT32_MAX-10U;
        mock_dwt.CYCCNT=200U; uint32_t start=FocPreempt_Begin();
        mock_dwt.CYCCNT=9200U; assert(FocPreempt_End(start,1U)==9000U);
        assert(deadline_snapshot.valid && deadline_snapshot.wall_cycles==9000U);
        assert(deadline_snapshot.preempt_total_cycles==0U &&
            deadline_snapshot.active_est_cycles==9000U && !mock_primask);
        mock_dwt.CYCCNT=9250U; FocPreempt_IrqEnd(source,lower);
    }
    assert(!foc_preempt_timing.invalid && !foc_preempt_timing.preempt_max);
    mock_priority[TIM2_IRQn+2]=1U; FocPreempt_CheckPriorities();
    assert(!foc_probe_priorities_ok && foc_probe_unexpected_irq);
    mock_priority[TIM2_IRQn+2]=3U; mock_priority[TIM6_DAC_IRQn+2]=1U;
    mock_enabled[TIM6_DAC_IRQn+2]=1U; FocPreempt_CheckPriorities();
    assert(!foc_probe_priorities_ok && foc_probe_unexpected_irq);
    puts("PASS lower encoder ledgers cannot pollute ADC attribution; wrong NVIC rejected");
}
