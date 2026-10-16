/* Low-perturbation boundary adapter, register mocks only. */
#include "main.h"
#include "foc_adc_timing_stm32.h"
#include "foc_adc_clock_stm32.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
TIM_TypeDef mock_tim;
ADC_TypeDef mock_adc1, mock_adc2;
DWT_Type mock_dwt;
uint32_t mock_primask, mock_ipsr;
uint32_t mock_hclk=170000000, mock_sysclk=170000000;
uint32_t mock_adc_clock_source=RCC_ADC12CLKSOURCE_SYSCLK;
ADC_Common_TypeDef mock_adc_common;
RCC_TypeDef mock_rcc;
uint32_t mock_frequency_reads;

static void frame(uint32_t now, uint32_t count, uint32_t work)
{
    mock_tim.CNT=count;
    mock_tim.CR1=TIM_COUNTERMODE_CENTERALIGNED1 | TIM_CR1_CEN | TIM_CR1_DIR;
    mock_dwt.CYCCNT=now;
    uint32_t start=FocAdcTiming_IrqEnter();
    mock_dwt.CYCCNT=now+work;
    FocAdcTiming_IrqExit(start);
    assert(!mock_primask);
}
static void contains(const char *cmd, const char *match)
{
    char text[192];
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
    frame(UINT32_MAX-49U,4200U,4000U); /* DWT wrap, not late. */
    contains("ADC BOUNDARY LITE","LATE=0 FIRST=0 WORST=0");
    frame(10000U,4000U,4100U); /* First late. */
    contains("ADC BOUNDARY LITE FIRST","VALID=1 SEQ=2 REM=4000 WALL=4100 OVER=100");
    frame(20000U,4000U,4200U); /* Worst changes, first stays frozen. */
    contains("ADC BOUNDARY LITE WORST","VALID=1 SEQ=3 REM=4000 WALL=4200 OVER=200");
    contains("ADC BOUNDARY LITE FIRST","VALID=1 SEQ=2");
    frame(30000U,4000U,4300U);
    contains("ADC BOUNDARY LITE","LATE=3 FIRST=1 WORST=1");
    mock_tim.CNT=FOC_ADC_TIMER_ARR+1U;
    frame(40000U,FOC_ADC_TIMER_ARR+1U,8000U); /* Invalid entry count. */
    contains("ADC BOUNDARY LITE WORST","VALID=1 SEQ=4");
    mock_dwt.CTRL=0;
    frame(50000U,4000U,9000U); /* DWT off cannot replace evidence. */
    contains("ADC BOUNDARY LITE WORST","VALID=1 SEQ=4");
    assert(!FocAdcTiming_RcActuationReady());
    FocWindowPlan plan;
    assert(FocAdcTiming_Prepare(.52f,.5f,.48f,&plan)==FOC_WINDOW_OK);
    uint32_t before=mock_tim.CCR1;
    assert(!FocAdcTiming_CommitBeforeBottom(&plan) && mock_tim.CCR1==before);
    char out[192];
    assert(!FocAdcTiming_Format("ADC BOUNDARY LITE BAD",out,sizeof out));
    assert(!FocAdcTiming_Format("ADC BOUNDARY LITE FIRST",out,4));
    mock_primask=1;
    contains("ADC BOUNDARY LITE FIRST","VALID=1 SEQ=2");
    assert(mock_primask==1);
    puts("PASS low-perturbation boundary adapter: freeze, wrap, no motion");
}
