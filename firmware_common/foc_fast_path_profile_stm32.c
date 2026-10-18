#include "main.h"
#include "foc_hot_path.h"
#include "foc_fast_path_profile.h"
#include "foc_irq_load.h"

/* Read these by the matching ELF after halting, or copy in task context.
 * No UART/printf, floating conversion, allocation, or protection side effects. */
FocPathProfile foc_path_profile;
/* Inclusive body maxima, not an exclusive sum: GUARD may nest in encoder.
 * source 0=TIM7, 1=TIM2 encoder, 2=RX DMA, 3=TX DMA. */
uint32_t foc_profile_irq_max[4],foc_profile_irq_calls[4];
static FocProfileFrame frame;
static uint32_t begin_wall,begin_irq,last_wall,last_irq;
FOC_RAM_PATH static void Stamp(uint32_t *wall,uint32_t *irq)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    *wall=DWT->CYCCNT; *irq=FocIrqLoad_Read();
    __set_PRIMASK(mask);
}
FOC_RAM_PATH void FocProfile_Begin(void)
{
    frame=(FocProfileFrame){0};
    Stamp(&begin_wall,&begin_irq); last_wall=begin_wall; last_irq=begin_irq;
}
FOC_RAM_PATH void FocProfile_Mark(unsigned stage)
{
    uint32_t wall,irq; Stamp(&wall,&irq);
    frame.wall[stage]+=wall-last_wall; frame.irq[stage]+=irq-last_irq;
    last_wall=wall; last_irq=irq;
}
FOC_RAM_PATH void FocProfile_End(uint8_t normal)
{
    FocProfile_Mark(FOC_PROF_OTHER);
    if (normal) FocProfile_Record(&foc_path_profile,&frame,
        last_wall-begin_wall,last_irq-begin_irq);
}
FOC_RAM_PATH void FocProfile_IrqRecord(unsigned source,uint32_t begin)
{
    uint32_t elapsed=DWT->CYCCNT-begin;
    ++foc_profile_irq_calls[source];
    if (elapsed>foc_profile_irq_max[source]) foc_profile_irq_max[source]=elapsed;
}
