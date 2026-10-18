/* Shared schedule, with a separately opted-in protected actuating candidate.
 * Historical hard-off profiles retain their original READY-only policy. */
#include "foc_pwm_pipeline.h"
_Static_assert(configPRIO_BITS==4U,"Pipeline priority audit assumes 4 NVIC bits");
_Static_assert(configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY==5U &&
    configMAX_SYSCALL_INTERRUPT_PRIORITY==0x50U,
    "Re-audit ADC/TIM7 no-RTOS call chains if syscall ceiling changes");
static FocPwmPending cl_pwm_pending;
uint32_t foc_pending_generated, foc_pending_held, foc_pending_empty;
uint32_t foc_pending_generation_max_cycles;
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
static uint32_t ProtectedLoop_PwmHealth(uint32_t now);
static uint32_t cl_pwm_neutral_commits;
static uint8_t ProtectedLoop_PwmNeutralReady(void)
{
    return cl_pwm_neutral_commits>=1000U &&
        !cl_late && !cl_current_cycles.deadline_miss_count &&
        FocAdcTiming_PipelineActuationReady();
}
FOC_RAM_PATH __attribute__((noinline,optimize("Os")))
unsigned ProtectedLoop_PwmCommitPermit(void)
{
    if (!cl_armed || !run_zero_cal_done || foc_fault ||
        cl_safety.protection.fault_flags || cl_safety.protection.result==FOC_OC_TRIPPED ||
        (cl_session.state!=CL_READY && cl_session.state!=CL_RUNNING)) return 0U;
    uint32_t now=AS5047P_DmaNowUs();
    uint32_t flags=ProtectedLoop_PwmHealth(now);
    if (flags) { ProtectedLoop_EmergencyOff(flags); return 0U; }
    if (ClSession_Expired(&cl_session,now)) { ProtectedLoop_Stop(); return 0U; }
    return cl_session.state==CL_RUNNING ? 2U : 1U;
}
#endif

void ProtectedLoop_PwmInvalidate(void)
{
    uint32_t saved=__get_PRIMASK(); __disable_irq();
    FocPwmPending_Invalidate(&cl_pwm_pending);
    __DMB(); __set_PRIMASK(saved);
}
static uint32_t ProtectedLoop_PwmMode(void)
{ return ((uint32_t)cl_session.state<<8U) | (uint32_t)motor_control_mode; }

/* First control action in ADC vector, after only the wall/IRQ timestamp.
 * No ADC data read, validation, HAL call or FOC computation precedes commit.
 * Guard revocation cannot race the three stores in the bounded transaction. */
FOC_RAM_PATH void ProtectedLoop_PwmEntry(void)
{
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
    /* READY computes for health evidence, but ONLY neutral is published.
     * START therefore cannot expose a shadow FOC command in the active CCR.
     * 1000 neutral commits span many real preload latch events. */
    if (cl_armed && cl_session.state==CL_READY && run_zero_cal_done &&
        !adc_fault && !foc_fault) {
        const uint16_t neutral[3]={(FOC_ADC_TIMER_ARR+1U)/2U,(FOC_ADC_TIMER_ARR+1U)/2U,
                                  (FOC_ADC_TIMER_ARR+1U)/2U};
        (void)FocPwmPending_Entry(&cl_pwm_pending,injected_seq_count+1U,
                                ProtectedLoop_PwmMode(),0U);
        if (!FocAdcTiming_PipelineCommit(neutral)) {
            if (cl_session.state!=CL_FAULT)
                ProtectedLoop_EmergencyOff(CL_COMPUTE_LATE);
        } else if (cl_pwm_neutral_commits<1000U) ++cl_pwm_neutral_commits;
        return;
    }
    uint8_t healthy=(uint8_t)(cl_armed && cl_session.state==CL_RUNNING &&
#else
    uint8_t healthy=(uint8_t)(cl_armed && cl_session.state==CL_READY &&
#endif
        run_zero_cal_done && !adc_fault && !foc_fault &&
        !cl_safety.protection.fault_flags &&
        cl_safety.protection.result!=FOC_OC_TRIPPED);
    if (FocPwmPending_Entry(&cl_pwm_pending,injected_seq_count+1U,
                            ProtectedLoop_PwmMode(),healthy)) {
        if (!FocAdcTiming_PipelineCommit(cl_pwm_pending.ccr))
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
            /* The commit predicate may already have consumed the lease with
             * a normal STOP, or latched the specific first fault. */
            if (cl_session.state!=CL_DONE && cl_session.state!=CL_FAULT)
#endif
            ProtectedLoop_EmergencyOff(CL_COMPUTE_LATE);
    } else ++foc_pending_empty;
}

FOC_RAM_PATH __attribute__((optimize("Os")))
static void ProtectedLoop_PwmStage(float du,float dv,float dw)
{
#if FOC_DETAIL_STATS
    uint32_t start=DWT->CYCCNT;
#endif
    FocAdcTiming_ProfileDutyPoint(); /* Separate hypothetical tail; read-only. */
    FocWindowPlan plan;
    FocWindowStatus status=FocAdcTiming_Prepare(du,dv,dw,&plan);
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
    /* CCR4 stays fixed. A plan needing a different trigger cannot certify
     * the currently programmed sampling window. Fail closed, don't move ADC. */
    if (status==FOC_WINDOW_OK && !FocAdcTiming_PipelinePlanMatches(&plan))
        status=FOC_WINDOW_TOO_SHORT;
#endif
    uint32_t saved=__get_PRIMASK(); __disable_irq();
    if (!cl_armed ||
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
        (cl_session.state!=CL_RUNNING && cl_session.state!=CL_READY) ||
#else
        cl_session.state!=CL_READY ||
#endif
        !run_zero_cal_done ||
        adc_fault || foc_fault || cl_safety.protection.result==FOC_OC_TRIPPED) {
        FocPwmPending_Invalidate(&cl_pwm_pending);
    } else if (status!=FOC_WINDOW_OK) {
        FocPwmPending_Invalidate(&cl_pwm_pending);
        FocAdcTiming_PlanFailed(status);
        ProtectedLoop_EmergencyOff(CL_BAD_ADC);
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
    } else if (cl_session.state==CL_READY) {
        /* Validate the shadow calculation too; discard only its publication,
         * never conceal a failed/nonfinite sampling-window plan. */
        FocPwmPending_Invalidate(&cl_pwm_pending);
#endif
    } else if (FocPwmPending_Stage(&cl_pwm_pending,cl_seq,
        ProtectedLoop_PwmMode(),cl_current_path==FOC_CURRENT_PATH_NORMAL,plan.phase)) {
        FOC_TRACE_CALL(FocCurrentTrace_Pwm());
        ++foc_pending_generated;
    }
    __set_PRIMASK(saved);
#if FOC_DETAIL_STATS
    uint32_t elapsed=DWT->CYCCNT-start;
    if (elapsed>foc_pending_generation_max_cycles)
        foc_pending_generation_max_cycles=elapsed;
#endif
}
