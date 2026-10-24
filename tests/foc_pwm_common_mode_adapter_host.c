#define FOC_COMMON_MODE_ADAPTER_TEST 1
#include "foc_pipeline_power_commit_host.c"
#undef main
#include "foc_pwm_common_mode.h"
extern FocPwmCommonModeDiag foc_pwm_common_mode_diag;
int main(void)
{
    char *args[]={"test",NULL};
    existing_pipeline_cases(1,args);
    mock_gpio.ODR=0; mock_tim.BDTR&=~TIM_BDTR_MOE; mock_tim.CCER=0;
    uint32_t ccr[4]={mock_tim.CCR1,mock_tim.CCR2,mock_tim.CCR3,mock_tim.CCR4};
    FocWindowPlan p;
    assert(FocAdcTiming_Prepare(.4450235664844513f,.5650515556335449f,
           .43494847416877747f,&p)==FOC_WINDOW_OK);
    assert(p.phase[0]==1804 && p.phase[1]==2314 && p.phase[2]==1761 && p.trigger==4184);
    assert(foc_pwm_common_mode_diag.last_offset==-87 && foc_pwm_common_mode_diag.adjusted);
    assert(foc_pwm_common_mode_diag.min_slack_ticks>=85);
    assert(FocAdcTiming_PipelinePlanMatches(&p));
    assert(FocAdcTiming_Prepare(.95f,.05f,.5f,&p)==FOC_WINDOW_TOO_SHORT);
    assert(!p.trigger && !p.phase[0] && foc_pwm_common_mode_diag.rejected);
    assert(mock_tim.CCR1==ccr[0] && mock_tim.CCR2==ccr[1] &&
           mock_tim.CCR3==ccr[2] && mock_tim.CCR4==ccr[3]);
    assert(!mock_gpio.ODR && !(mock_tim.BDTR&TIM_BDTR_MOE) && !mock_tim.CCER);
    puts("PASS common-mode actual Prepare adapter: plan only, no CCR/gate write");
    return 0;
}
