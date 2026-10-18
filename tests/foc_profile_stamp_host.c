#include "main.h"
#include "foc_fast_path_profile.h"
#include <assert.h>
#include <stdio.h>
DWT_Type mock_dwt;
uint32_t mock_primask;
static uint32_t irq_total;
uint32_t FocIrqLoad_Read(void) { assert(mock_primask); return irq_total; }
extern FocPathProfile foc_path_profile;
extern uint32_t foc_profile_irq_max[4],foc_profile_irq_calls[4];
int main(void)
{
    mock_dwt.CYCCNT=UINT32_MAX-9U;
    FocProfile_Begin();
    mock_dwt.CYCCNT=90U; irq_total=30U;
    FocProfile_Mark(FOC_PROF_ADC);
    mock_dwt.CYCCNT=190U; irq_total=50U;
    FocProfile_Mark(FOC_PROF_VALIDATE);
    mock_dwt.CYCCNT=290U;
    FocProfile_End(1U);
    assert(!mock_primask && foc_path_profile.frames==1U);
    assert(foc_path_profile.normal_total_max==300U && foc_path_profile.normal_cpu_max==250U);
    assert(foc_path_profile.wall_max[FOC_PROF_ADC]==100U);
    assert(foc_path_profile.cpu_max[FOC_PROF_ADC]==70U);
    assert(foc_path_profile.worst_irq==50U);
    FocProfile_Begin(); mock_dwt.CYCCNT+=9000U; FocProfile_End(0U);
    assert(foc_path_profile.frames==1U && foc_path_profile.normal_total_max==300U);
    FocProfile_IrqRecord(0U,mock_dwt.CYCCNT-123U);
    assert(foc_profile_irq_max[0]==123U && foc_profile_irq_calls[0]==1U);
    mock_primask=1U; FocProfile_Begin(); FocProfile_End(1U); assert(mock_primask==1U);
    puts("PASS production DWT stamps: wrap / same-interval IRQ attribution / normal-only / PRIMASK");
    return 0;
}
