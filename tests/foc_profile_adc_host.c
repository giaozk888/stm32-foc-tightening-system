/* Production CCR transaction observer under register mocks, not timing data. */
#define main unused_prior_commit_main
#include "foc_rc_commit_host.c"
#undef main
#include "foc_pwm_write_probe.h"
extern FocPwmWriteProbe foc_pwm_write_profile,foc_pwm_duty_profile;
int main(void)
{
    mock_tim.ARR=4249U; mock_tim.BDTR=85U;
    mock_tim.CR1=TIM_COUNTERMODE_CENTERALIGNED1;
    mock_tim.CCMR1=TIM_CCMR1_OC1PE|TIM_CCMR1_OC2PE;
    mock_tim.CCMR2=TIM_CCMR2_OC3PE|TIM_CCMR2_OC4PE;
    mock_tim.CR2=TIM_TRGO2_OC4REF;
    mock_adc_common.CCR=FOC_ADC_CLOCK_PRESCALER;
    assert(FocAdcTiming_Commit(.5f,.5f,.5f)==FOC_WINDOW_OK);
    assert(FocAdcTiming_CertifyClock());
    mock_tim.CR1|=TIM_CR1_CEN|TIM_CR1_DIR;
    mock_tim.CNT=4200U; mock_dwt.CTRL=1U; mock_dwt.CYCCNT=1000U;
    uint32_t start=FocAdcTiming_IrqEnter();
    mock_tim.CNT=4000U; mock_dwt.CYCCNT=1200U;
    FocAdcTiming_ProfileDutyPoint();
    assert(foc_pwm_duty_profile.points==1U && !foc_pwm_duty_profile.writes);
    assert(!foc_pwm_write_profile.points && !foc_pwm_write_profile.writes);
    FocWindowPlan plan; assert(FocAdcTiming_Prepare(.5f,.5f,.5f,&plan)==FOC_WINDOW_OK);
    mock_ipsr=34U;
    assert(FocAdcTiming_CommitBeforeBottom(&plan));
    assert(foc_pwm_write_profile.points==1U && foc_pwm_write_profile.writes==1U);
    assert(foc_pwm_write_profile.pwm_update_margin_ticks_min==4000);
    assert(!mock_primask && !(mock_tim.CR1&TIM_CR1_UDIS));
    mock_dwt.CYCCNT=6000U; mock_tim.CNT=800U; mock_tim.CR1&=~TIM_CR1_DIR;
    uint32_t before=mock_tim.CCR1;
    assert(!FocAdcTiming_CommitBeforeBottom(&plan));
    assert(mock_tim.CCR1==before && foc_pwm_write_profile.writes==1U);
    FocAdcTiming_IrqExit(start);
    FocAdcTiming_ProfileDutyPoint();
    assert(foc_pwm_duty_profile.late_update_count==1U);
    puts("PASS actual CCR observer: valid transaction / rejected no-write / separate hard-off probe");
}
