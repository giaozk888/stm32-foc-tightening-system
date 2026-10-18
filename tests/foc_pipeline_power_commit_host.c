/* Actual register adapter: never talks to hardware. */
#define main old_adapter_cases
#include "foc_rc_commit_host.c"
#undef main
#undef assert
#define assert(condition) do { if (!(condition)) { \
    fprintf(stderr,"assertion failed: %s:%d: %s\n",__FILE__,__LINE__,#condition); \
    exit(101); } } while (0)
#include "foc_preempt_probe.h"
#include "foc_pwm_write_probe.h"
ProbeGpio mock_gpio;
volatile uint32_t foc_probe_priorities_ok=1U,foc_probe_unexpected_irq;
volatile FocPreTiming foc_preempt_timing;
extern FocPwmWriteProbe foc_pwm_write_profile;
extern uint32_t foc_ccr_probe_blocked,foc_ccr_probe_post_unsafe;
static unsigned permission=2U,break_during_write;
unsigned ProtectedLoop_PwmCommitPermit(void) { return permission; }
void mock_barrier(void)
{
    if (break_during_write) { mock_tim.BDTR&=~TIM_BDTR_MOE; break_during_write=0U; }
}
int main(int argc,char **argv)
{
    unsigned which=argc==2 ? (unsigned)strtoul(argv[1],NULL,10) : 0U;
    mock_tim.ARR=FOC_ADC_TIMER_ARR; mock_tim.BDTR=85U;
    mock_tim.CR1=TIM_COUNTERMODE_CENTERALIGNED1;
    mock_tim.CCMR1=TIM_CCMR1_OC1PE|TIM_CCMR1_OC2PE;
    mock_tim.CCMR2=TIM_CCMR2_OC3PE|TIM_CCMR2_OC4PE;
    mock_tim.CR2=TIM_TRGO2_OC4REF; mock_adc_common.CCR=FOC_ADC_CLOCK_PRESCALER;
    assert(FocAdcTiming_Commit(.5f,.5f,.5f)==FOC_WINDOW_OK);
    assert(FocAdcTiming_CertifyClock());
    mock_tim.CR1|=TIM_CR1_CEN|TIM_CR1_DIR; mock_tim.CNT=4000U;
    mock_dwt.CTRL=1U; mock_dwt.CYCCNT=1000U; mock_ipsr=34U;
    mock_gpio.ODR=DRIVER_SD_Pin; mock_tim.BDTR|=TIM_BDTR_MOE; mock_tim.CCER=0x555U;
    uint16_t phase[3]={2200U,2100U,2000U};
    uint32_t neutral=mock_tim.CCR1,cr1=mock_tim.CR1,ccr4=mock_tim.CCR4;
    if (which==1U) permission=0U;
    if (which==2U) mock_tim.BDTR&=~TIM_BDTR_MOE;
    if (which==3U) mock_gpio.ODR=0U;
    if (which==4U) mock_tim.CCER=0U;
    if (which==5U) mock_tim.BDTR|=TIM_BDTR_AOE;
    if (which==6U) { permission=1U; mock_gpio.ODR=0U; mock_tim.BDTR&=~TIM_BDTR_MOE; mock_tim.CCER=0U; }
    if (which==7U) mock_tim.CNT=170U;
    if (which==8U) break_during_write=1U;
    unsigned success=which==0U || which==6U || which==9U;
    assert(FocAdcTiming_PipelineCommit(phase)==(int)success);
    assert(mock_tim.CCR4==ccr4 && mock_tim.CR1==cr1);
    if (!success && which!=8U) {
        assert(mock_tim.CCR1==neutral && !foc_pwm_write_profile.points);
        assert(foc_ccr_probe_blocked==1U);
    }
    if (which==8U) assert(!(mock_tim.BDTR&TIM_BDTR_MOE) && foc_ccr_probe_post_unsafe==1U);
    if (success) assert(mock_tim.CCR1==phase[0] && foc_pwm_write_profile.points==1U);
    /* Fixed CCR4 must match the planner; this never silently moves ADC. */
    FocWindowPlan p; assert(FocAdcTiming_Prepare(.52f,.50f,.48f,&p)==FOC_WINDOW_OK);
    assert(FocAdcTiming_PipelinePlanMatches(&p));
    ++p.trigger; assert(!FocAdcTiming_PipelinePlanMatches(&p));
    if (which==9U) {
        /* Tail diagnostic may warn, but entry commits + wall deadline are
         * the candidate's REAL timing admission, with no counter clearing. */
        mock_gpio.ODR=0U; mock_tim.BDTR&=~TIM_BDTR_MOE; mock_tim.CCER=0U;
        permission=1U; phase[0]=phase[1]=phase[2]=(uint16_t)neutral;
        assert(!FocAdcTiming_PipelineActuationReady());
        for (unsigned i=0U;i<1000U;++i) {
            assert(FocAdcTiming_PipelineCommit(phase));
            FocAdcTiming_RecordRaw(1551U,1551U);
        }
        uint32_t stamp=FocAdcTiming_IrqEnter(); mock_dwt.CYCCNT+=5000U;
        FocAdcTiming_IrqExit(stamp); mock_tim.CNT=4000U;
        assert(FocAdcTiming_PipelineActuationReady());
        foc_preempt_timing.deadline_miss=1U;
        assert(!FocAdcTiming_PipelineActuationReady());
    }
    puts("PASS actuating CCR permit / no gate resurrection / fixed ADC window / timing admission");
}
