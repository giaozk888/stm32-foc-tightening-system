#include <assert.h>
#include <stdio.h>
#include "main.h"
#include "foc_irq_load.h"
MockDwt irq_mock_dwt;
uint32_t irq_mock_mask;
int main(void)
{
    FocIrqSourceFrame frame; FocIrqSourceStats stats;
    irq_mock_mask=1U; FocIrqSource_FrameBegin(); assert(irq_mock_mask==1U);
    DWT->CYCCNT=100U; FocIrqSource_Enter(FOC_IRQ_TIMER); assert(irq_mock_mask==1U);
    irq_mock_mask=0U;
    DWT->CYCCNT=110U; FocIrqSource_Enter(FOC_IRQ_GUARD); assert(!irq_mock_mask);
    DWT->CYCCNT=125U; FocIrqSource_Leave(FOC_IRQ_GUARD); assert(!irq_mock_mask);
    DWT->CYCCNT=140U; FocIrqSource_Leave(FOC_IRQ_TIMER);
    assert(FocIrqLoad_Read()==40U && !irq_mock_mask);
    FocIrqSource_FrameEnd(&frame); FocIrqSource_Stats(&stats);
    assert(!frame.error && frame.cycles[0]==15U && frame.cycles[1]==25U);
    assert(stats.max_inclusive[1]==40U && stats.calls[0]==1U && !irq_mock_mask);
    irq_mock_mask=1U; FocIrqSource_Stats(&stats); assert(irq_mock_mask==1U);
    FocIrqSource_FrameBegin(); FocIrqSource_FrameEnd(0); assert(irq_mock_mask==1U);
    puts("PASS production IRQ adapter: shared timestamps, nested union, PRIMASK restoration");
    return 0;
}
