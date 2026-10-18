#define main old_attribution_main_not_run
#include "foc_preempt_attribution_host.c"
#undef main
uint32_t foc_pending_commit_max_cycles, foc_pending_generation_max_cycles;
int main(void)
{
    for (unsigned i=0;i<104U;++i) mock_priority[i]=15U;
    mock_priority[TIM7_DAC_IRQn+2]=3U;
    mock_priority[ADC1_2_IRQn+2]=2U;
    mock_priority[TIM2_IRQn+2]=mock_priority[DMA1_Channel4_IRQn+2]=
        mock_priority[DMA1_Channel5_IRQn+2]=1U;
    mock_enabled[TIM7_DAC_IRQn+2]=mock_enabled[TIM2_IRQn+2]=
        mock_enabled[DMA1_Channel4_IRQn+2]=mock_enabled[DMA1_Channel5_IRQn+2]=1U;
    FocPreempt_CheckPriorities(); assert(foc_probe_priorities_ok);
    mock_dwt.CYCCNT=100U; FocPreToken guard=FocPreempt_IrqBegin(0U);
    mock_ipsr=34U; mock_dwt.CYCCNT=120U;
    uint32_t start=FocPreempt_Begin();
    mock_dwt.CYCCNT=130U; FocPreToken encoder=FocPreempt_IrqBegin(1U);
    mock_dwt.CYCCNT=150U; FocPreempt_IrqEnd(1U,encoder);
    mock_dwt.CYCCNT=220U; FocPreempt_End(start,1U);
    mock_dwt.CYCCNT=250U; FocPreempt_IrqEnd(0U,guard);
    assert(foc_preempt_timing.wall_max==100U && foc_preempt_timing.preempt_max==20U);
    assert(foc_preempt_timing.active_est_max==80U &&
        !foc_preempt_timing.worst_preempt.cycles[0] &&
        foc_preempt_timing.worst_preempt.cycles[1]==20U);
    assert(foc_preempt_irq[0].cycles==150U); /* service wall, never ADC preempt */
    mock_ipsr=0U; FocPreempt_Monitor();
    assert(strstr(output,"tim7_preempt_max_us=0.000") &&
        strstr(output,"SERVICE_WALL_INCLUDING_CHILDREN TIM7"));
    puts("PASS lower TIM7 cannot pollute ADC exclusive preemption / encoder retained");
}
