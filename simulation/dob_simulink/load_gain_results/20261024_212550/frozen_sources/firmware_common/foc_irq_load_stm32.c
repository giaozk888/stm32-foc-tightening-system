#include "main.h"
#include "foc_irq_load.h"
#include "foc_hot_path.h"
static FocIrqLoad measured;
#if defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
static FocIrqSources sources;
FOC_RAM_PATH void FocIrqSource_Enter(unsigned id)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint32_t now=DWT->CYCCNT;
    FocIrqLoad_Begin(&measured,now); FocIrqSources_Enter(&sources,id,now);
    __set_PRIMASK(mask);
}
FOC_RAM_PATH void FocIrqSource_Leave(unsigned id)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint32_t now=DWT->CYCCNT;
    FocIrqLoad_End(&measured,now); FocIrqSources_Leave(&sources,id,now);
    __set_PRIMASK(mask);
}
FOC_RAM_PATH void FocIrqSource_FrameBegin(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    FocIrqSources_FrameBegin(&sources);
    __set_PRIMASK(mask);
}
FOC_RAM_PATH void FocIrqSource_FrameEnd(FocIrqSourceFrame *out)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    FocIrqSources_FrameEnd(&sources,out);
    __set_PRIMASK(mask);
}
void FocIrqSource_Stats(FocIrqSourceStats *out)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    for (unsigned i=0U;i<FOC_IRQ_SOURCE_N;++i) {
        out->cycles[i]=sources.stats.cycles[i]; out->calls[i]=sources.stats.calls[i];
        out->max_inclusive[i]=sources.stats.max_inclusive[i];
    }
    out->error=sources.stats.error;
    __set_PRIMASK(mask);
}
#endif
FOC_RAM_PATH void FocIrqLoad_Enter(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    FocIrqLoad_Begin(&measured,DWT->CYCCNT);
    __set_PRIMASK(mask);
}
FOC_RAM_PATH void FocIrqLoad_Leave(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    FocIrqLoad_End(&measured,DWT->CYCCNT);
    __set_PRIMASK(mask);
}
FOC_RAM_PATH uint32_t FocIrqLoad_Read(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint32_t result=FocIrqLoad_Total(&measured,DWT->CYCCNT);
    __set_PRIMASK(mask); return result;
}
