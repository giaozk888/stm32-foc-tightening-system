/* Real timing and IRQ-source adapters, register mocks only. */
#include "main.h"
#include "foc_adc_timing_stm32.h"
#include "foc_adc_clock_stm32.h"
#include "foc_irq_load.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
TIM_TypeDef mock_tim;
ADC_TypeDef mock_adc1, mock_adc2;
DWT_Type mock_dwt;
uint32_t mock_primask, mock_ipsr;
uint32_t mock_hclk=170000000, mock_sysclk=170000000;
uint32_t mock_adc_clock_source=RCC_ADC12CLKSOURCE_SYSCLK;
ADC_Common_TypeDef mock_adc_common;
RCC_TypeDef mock_rcc;
uint32_t mock_frequency_reads;

static void frame(uint32_t now, uint32_t count, uint32_t down, uint32_t work)
{
    mock_tim.CNT=count;
    mock_tim.CR1=TIM_COUNTERMODE_CENTERALIGNED1 | TIM_CR1_CEN | (down ? TIM_CR1_DIR : 0U);
    mock_dwt.CYCCNT=now;
    uint32_t start=FocAdcTiming_IrqEnter();
    mock_dwt.CYCCNT=now+10U;
    FocIrqSource_Enter(FOC_IRQ_TIMER);
    mock_dwt.CYCCNT=now+20U;
    FocIrqSource_Enter(FOC_IRQ_GUARD);
    mock_dwt.CYCCNT=now+40U;
    FocIrqSource_Leave(FOC_IRQ_GUARD);
    mock_dwt.CYCCNT=now+60U;
    FocIrqSource_Leave(FOC_IRQ_TIMER);
    mock_dwt.CYCCNT=now+work;
    mock_tim.CNT=12U;
    FocAdcTiming_IrqExit(start);
    assert(!mock_primask);
}
static void contains(const char *cmd, const char *match)
{
    char text[192]; /* Same payload capacity as Protocol_HandleLine. */
    assert(FocAdcTiming_Format(cmd,text,sizeof text));
    assert(strstr(text,match));
}
int main(void)
{
    mock_tim.ARR=FOC_ADC_TIMER_ARR; mock_tim.BDTR=85;
    mock_tim.CR1=TIM_COUNTERMODE_CENTERALIGNED1;
    mock_tim.CCMR1=TIM_CCMR1_OC1PE | TIM_CCMR1_OC2PE;
    mock_tim.CCMR2=TIM_CCMR2_OC3PE | TIM_CCMR2_OC4PE;
    mock_tim.CR2=TIM_TRGO2_OC4REF;
    mock_adc_common.CCR=FOC_ADC_CLOCK_PRESCALER;
    assert(FocAdcTiming_Commit(.5f,.5f,.5f)==FOC_WINDOW_OK);
    assert(FocAdcTiming_CertifyClock());
    mock_dwt.CTRL=1;
    frame(UINT32_MAX-49U,4200U,1U,4000U); /* DWT wrap, margin +200. */
    contains("ADC BOUNDARY WORST","REM=4200 WALL=4000 IRQ=50 CPU=3950 MARGIN=200");
    contains("ADC BOUNDARY WORST IRQ","CYC=20,30,0,0 CNT=1,1,0,0");
    contains("ADC BOUNDARY FIRST","VALID=0");
    frame(10000U,4000U,1U,4100U); /* First late, -100. */
    contains("ADC BOUNDARY FIRST","VALID=1 SEQ=2");
    contains("ADC BOUNDARY FIRST","MARGIN=-100");
    frame(20000U,4000U,1U,4200U); /* Worst changes, first is frozen. */
    contains("ADC BOUNDARY WORST","VALID=1 SEQ=3");
    contains("ADC BOUNDARY FIRST","VALID=1 SEQ=2");
    frame(30000U,4200U,0U,4200U); /* Upcount: 8498-4200=4298, not 4200. */
    contains("ADC BOUNDARY","FRAMES=4 INVALID=0 LATE=2");
    mock_tim.RCR=1;
    assert(!FocAdcTiming_CanStart() && !FocAdcTiming_FastCanStart());
    frame(40000U,4000U,1U,6000U); /* Invalid geometry cannot replace evidence. */
    contains("ADC BOUNDARY","FRAMES=5 INVALID=1 LATE=2");
    contains("ADC BOUNDARY WORST","VALID=1 SEQ=3");
    mock_tim.RCR=0;
    mock_dwt.CTRL=0;
    frame(50000U,4000U,1U,6000U);
    contains("ADC BOUNDARY","INVALID=2");
    assert(!FocAdcTiming_RcActuationReady()); /* Probe never admits motion. */
    FocWindowPlan plan;
    assert(FocAdcTiming_Prepare(.52f,.5f,.48f,&plan)==FOC_WINDOW_OK);
    uint32_t before=mock_tim.CCR1;
    assert(!FocAdcTiming_CommitBeforeBottom(&plan) && mock_tim.CCR1==before);
    char out[192];
    assert(!FocAdcTiming_Format("ADC BOUNDARY BAD",out,sizeof out));
    assert(!FocAdcTiming_Format("ADC BOUNDARY FIRST",out,4));
    mock_primask=1;
    contains("ADC BOUNDARY FIRST IRQ","VALID=1 SEQ=2");
    assert(mock_primask==1);
    puts("PASS real boundary adapters: same-frame nested attribution, freeze, geometry, wrap, no motion");
}
