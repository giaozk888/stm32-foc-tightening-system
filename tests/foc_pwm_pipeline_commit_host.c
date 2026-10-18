/* Production register adapter; no physical timing or hardware access. */
#define main old_commit_main_not_run
#include "foc_rc_commit_host.c"
#undef main
#include "foc_preempt_probe.h"
#include "foc_pwm_write_probe.h"
ProbeGpio mock_gpio;
volatile uint32_t foc_probe_priorities_ok=1U,foc_probe_unexpected_irq;
extern FocPwmWriteProbe foc_pwm_write_profile;
extern uint32_t foc_ccr_probe_hard_late,foc_ccr_probe_post_unsafe;
static uint32_t advance, stop_during_write;
void mock_barrier(void)
{
    if (advance) {
        /* Observation must not modify timer update semantics. */
        assert(!(mock_tim.CR1 & TIM_CR1_UDIS));
        mock_dwt.CYCCNT+=advance;
        advance=0U;
        if (stop_during_write) mock_tim.CR1&=~TIM_CR1_CEN;
    }
}
int main(int argc,char **argv)
{
    unsigned which=argc==2 ? (unsigned)strtoul(argv[1],NULL,10) : 0U;
    mock_tim.ARR=4249U; mock_tim.BDTR=85U;
    mock_tim.CR1=TIM_COUNTERMODE_CENTERALIGNED1;
    mock_tim.CCMR1=TIM_CCMR1_OC1PE|TIM_CCMR1_OC2PE;
    mock_tim.CCMR2=TIM_CCMR2_OC3PE|TIM_CCMR2_OC4PE;
    mock_tim.CR2=TIM_TRGO2_OC4REF;
    mock_adc_common.CCR=FOC_ADC_CLOCK_PRESCALER;
    assert(FocAdcTiming_Commit(.5f,.5f,.5f)==FOC_WINDOW_OK);
    assert(FocAdcTiming_CertifyClock());
    mock_tim.CR1|=TIM_CR1_CEN|TIM_CR1_DIR;
    mock_tim.CNT=4000U; mock_dwt.CTRL=1U; mock_dwt.CYCCNT=1000U;
    mock_ipsr=34U;
    uint16_t phase[3]={2200U,2100U,2000U};
    uint32_t ccr4=mock_tim.CCR4,egr=mock_tim.EGR;
    uint32_t old[3]={mock_tim.CCR1,mock_tim.CCR2,mock_tim.CCR3};
    if (which==1U) phase[0]=4250U;
    if (which==2U) mock_gpio.ODR=DRIVER_SD_Pin;
    if (which==3U) mock_tim.BDTR|=TIM_BDTR_MOE;
    if (which==4U) mock_tim.CCER=1U;
    if (which==5U) mock_dwt.CTRL=0U;
    if (which==6U) mock_tim.CR1&=~TIM_CR1_DIR;
    if (which==7U) mock_tim.CNT=170U;
    if (which==8U) mock_tim.CR1|=TIM_CR1_UDIS;
    if (which==9U) foc_probe_priorities_ok=0U;
    if (which==10U) mock_ipsr=0U;
    if (which==12U) mock_primask=1U;
    /* At DMB, after the three actual stores: test late observation and
     * asynchronous revocation without ever opening SD/MOE. */
    if (which==11U) advance=5000U;
    if (which==14U) { advance=25U; stop_during_write=1U; }
    uint32_t cr1=mock_tim.CR1,mask=mock_primask;
    int good=which==0U || which==12U;
    assert(FocAdcTiming_PipelineCommit(which==13U ? NULL : phase)==good);
    assert(mock_primask==mask && mock_tim.CCR4==ccr4 && mock_tim.EGR==egr);
    assert((mock_tim.CR1 & TIM_CR1_UDIS)==(cr1 & TIM_CR1_UDIS));
    if (good || which==11U || which==14U) {
        assert(mock_tim.CCR1==phase[0] && mock_tim.CCR2==phase[1] && mock_tim.CCR3==phase[2]);
#if FOC_HEAVY_PROFILE_ENABLE
        assert(foc_pwm_write_profile.writes==1U);
#endif
    } else {
        assert(mock_tim.CCR1==old[0] && mock_tim.CCR2==old[1] && mock_tim.CCR3==old[2]);
        assert(!foc_pwm_write_profile.writes);
    }
    if (good) assert(foc_pwm_write_profile.points==1U &&
        foc_pwm_write_profile.pwm_update_margin_ticks_min==4000);
    if (which==11U) assert(foc_ccr_probe_hard_late==1U &&
        foc_pwm_write_profile.pwm_update_margin_ticks_min==-1000);
    if (which==14U) {
        assert(foc_ccr_probe_post_unsafe==1U);
#if FOC_HEAVY_PROFILE_ENABLE
        assert(foc_pwm_write_profile.invalid==1U);
#endif
    }
    puts("PASS pipeline actual CCR / guard / no UDIS / separate late and invalid / no power enable");
}
