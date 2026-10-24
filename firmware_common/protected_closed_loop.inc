/* Separate opt-in, single local 20 rpm / 400 ms motor trial. No boot actuation,
 * no arbitrary setpoints, no fault-clear or auto-retry. TIM7 is independent of
 * both ADC and the 1 kHz outer task. Hardware OCP is not fabricated/disabled.
 * Included after original control declarations; original PIs are reused. */
#include "foc_feedback_safety_candidate.h"
#include "foc_feedback_guard_stm32.h"
#include "foc_zero_median.h"
#include "foc_hot_path.h"
#include "foc_fast_path_profile.h"
#include "foc_preempt_probe.h"
#if defined(FOC_RC_DEFERRED_SHADOW)
#include "foc_rc_deferred_plan.h"
static FocRcDeferredPlan cl_deferred_plan;
static uint32_t cl_deferred_staged,cl_deferred_taken,cl_deferred_empty;
static uint32_t cl_deferred_stale,cl_deferred_unsafe,cl_deferred_rejected;
static uint32_t cl_deferred_plan_fail;
#endif
#if defined(FOC_GUARD_FAST_PATH)
#include "foc_guard_integer.h"
#endif
static ClSession cl_session;
#if defined(FOC_TORQUE_CHAIN_DIAG)
static FocTorqueChainDiag torque_diag;
#if defined(FOC_ANGLE_CHAIN_DIAG)
static FocAngleHand angle_hand;
#endif
static int TorqueChain_Command(const char *cmd,char *out,size_t size);
#endif
static FocFeedbackSafety cl_safety;
static FocFeedbackFrame cl_frame;
static FocZeroCal cl_zero;
static FocZeroMedian cl_zero_filter;
static uint32_t cl_seq, cl_last_us, cl_guard_us, cl_psc, cl_irqs;
static uint32_t cl_work_n, cl_work_max, cl_late, cl_outer_n, cl_off_us;
#if defined(FOC_FAST_CURRENT_REJECT)
static FocCurrentCycleStats cl_current_cycles;
static uint8_t cl_current_path; /* FOC_CURRENT_PATH_*; 0 startup/safety fault. */
#endif
#if defined(FOC_FAST_MATH)
static uint32_t cl_cpu_max_cyc, cl_preempt_max_cyc;
static uint32_t cl_pair_max_us, cl_math_max_us;
#endif
#if defined(FOC_PAIR_FAST_PATH)
static FocFrameCost cl_frame_cost, cl_late_cost;
#endif
#if defined(FOC_IRQ_SOURCE_TRACE)
static FocIrqSourceFrame cl_frame_irq, cl_late_irq;
#endif
static uint32_t cl_stop_us, cl_fault_seq, cl_fault_last_us, cl_flags;
static uint16_t cl_fault_u, cl_fault_v, cl_last_u, cl_last_v;
static uint8_t cl_armed, cl_initialized, cl_fault_valid, cl_request;
/* Immutable for this boot: metadata changes only through reset/bootloader.
 * Do not CRC Flash metadata from the 25 us guard or a PRIMASK section. */
static uint8_t cl_boot_confirmed;
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
static FocTimeoutEvidence cl_direct_timeout;
__attribute__((noinline,cold,optimize("Oz")))
static void FaultDiag_DirectTimeout(FocTimeoutReason reason,uint32_t now,
                                   uint32_t reference,uint32_t limit)
{
    cl_direct_timeout=(FocTimeoutEvidence){reason,now,reference,
        now-reference,limit,cl_last_us,0U,0U,0U};
}
__attribute__((noinline,cold,optimize("Oz")))
static void FaultDiag_FillProtected(volatile FocFaultSnapshot *s)
{
    const FocFilteredProtection *p=&cl_safety.protection;
    if (p->timeout.reason) {
        const FocTimeoutLatch *t=&p->timeout;
        s->timeout=(FocTimeoutEvidence){t->reason,t->now_us,t->reference_us,
            t->now_us-t->reference_us,t->limit_us,p->last_us,p->pending_us,p->pending,p->misses};
    } else if (cl_direct_timeout.reason) s->timeout=cl_direct_timeout;
    if (s->timeout.reason) s->timeout_reason=s->timeout.reason;
#if defined(FOC_FAST_CURRENT_REJECT)
    const FocCurrentValidation *v=&cl_safety.validation;
    s->evidence_present=1U; s->current_validator_state=v->state;
    _Static_assert(offsetof(FocCurrentValidation,current_unresolved_max_consecutive)-
        offsetof(FocCurrentValidation,current_suspect_total)==20U,"validator diagnostic layout");
    __builtin_memcpy((void *)&s->current_suspect_total,&v->current_suspect_total,24U);
    s->foc_cycles_max=cl_current_cycles.max_cycles;
    s->foc_normal_cycles_max=cl_current_cycles.normal_max_cycles;
    s->foc_suspect_cycles_max=cl_current_cycles.suspect_max_cycles;
    s->foc_unresolved_cycles_max=cl_current_cycles.unresolved_max_cycles;
    s->foc_deadline_miss_count=cl_current_cycles.deadline_miss_count;
#endif
}
#if defined(FOC_FAST_CURRENT_REJECT)
static uint32_t FaultDiag_CurrentSamples(void)
{ return cl_safety.validation.current_samples_total; }
#endif
#endif
static void FOC_ResetController(void);
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s);
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
FOC_RAM_PATH static void ProtectedLoop_Stop(void);
#endif
#include "foc_pwm_pipeline_binding.inc"
#endif
#if defined(FOC_STARTUP_TRACE)
#include "foc_startup_trace_binding.inc"
#endif

#if defined(FOC_OUTPUT_GATE_EVIDENCE)
#include "foc_output_gate_evidence_binding.inc"
#endif
FOC_COMPACT_HELPER uint8_t ProtectedLoop_GatesMatch(void)
{
#if defined(FOC_OUTPUT_GATE_EVIDENCE)
    return ProtectedLoop_GatesObserved();
#else
    uint32_t sd=(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin)!=0U;
    uint32_t moe=TIM1->BDTR & TIM_BDTR_MOE;
    if (!(TIM1->CR1 & TIM_CR1_CEN) || (TIM1->BDTR & TIM_BDTR_AOE)) return 0U;
    return cl_session.state==CL_RUNNING ?
        (sd && moe && TIM1->CCER==0x555U) : (!sd && !moe && !TIM1->CCER);
#endif
}
FOC_COMPACT_HELPER uint8_t ProtectedLoop_TimerHealthy(void)
{
#if defined(AS5047P_DMA_FOC_FIRST)
    /* This opt-in profile deliberately places encoder events below ADC.
     * Check the selected configuration; do not accept arbitrary drift. */
    const uint32_t adc_priority = 2U;
    const uint32_t encoder_priority = 3U;
#elif defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
    const uint32_t adc_priority = 2U;
    const uint32_t encoder_priority = 1U;
#else
    const uint32_t adc_priority = 1U;
#endif
    return (RCC->APB1ENR1 & (RCC_APB1ENR1_TIM2EN | RCC_APB1ENR1_TIM7EN)) ==
        (RCC_APB1ENR1_TIM2EN | RCC_APB1ENR1_TIM7EN) &&
        (TIM2->CR1 & TIM_CR1_CEN) && TIM2->PSC==cl_psc && TIM2->ARR==UINT32_MAX &&
        TIM7->PSC==cl_psc && TIM7->ARR==24U && TIM7->DIER==TIM_DIER_UIE &&
        (TIM7->CR1 & (TIM_CR1_CEN | TIM_CR1_URS | TIM_CR1_OPM))==(TIM_CR1_CEN | TIM_CR1_URS) &&
        NVIC_GetPriority(TIM7_DAC_IRQn)==FOC_SOFTWARE_GUARD_PRIORITY && NVIC_GetPriority(ADC1_2_IRQn)==adc_priority &&
#if defined(AS5047P_DMA_FOC_FIRST) || defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
        NVIC_GetPriority(TIM2_IRQn)==encoder_priority &&
        NVIC_GetPriority(DMA1_Channel4_IRQn)==encoder_priority &&
        NVIC_GetPriority(DMA1_Channel5_IRQn)==encoder_priority &&
#endif
        NVIC_GetEnableIRQ(TIM7_DAC_IRQn);
}
/* Fault paths close registers BEFORE timestamps or math. Can be called before
 * initialization, including HardFault/NMI. No HAL waits/RTOS/DMA cleanup. */
FOC_RAM_PATH void ProtectedLoop_EmergencyOff(uint32_t flags)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    FocFeedbackGuard_OutputOff();
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    FocPwmPending_Invalidate(&cl_pwm_pending);
#endif
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
    if (flags & CL_OUTER_STALE)
        FaultDiag_DirectTimeout(FOC_TO_OUTER_CONTROL,AS5047P_DmaNowUs(),
            cl_session.outer_us,CL_OUTER_DEADLINE_US);
    /* Record the same final reason that the existing Trip below will latch. */
    if (!foc_fault_snapshot.valid) foc_fault_snapshot.protection_flags=cl_safety.protection.fault_flags|flags;
    FaultDiag_Capture(FOC_DIAG_PROTECTION,
        cl_safety.protection.result==FOC_OC_TRIPPED ? cl_safety.protection.reason : FOC_FP_HEALTH,
        (flags & CL_OUTER_STALE) ? FOC_TO_OUTER_CONTROL :
        (flags & CL_BAD_ENCODER) ? encoder_timeout_reason :
        (flags & CL_COMPUTE_LATE) ? FOC_TO_COMPUTE_DEADLINE : FOC_TO_NONE,
        tightening_test_elapsed_ms,0U);
#endif
    cl_armed=0U; FocFeedbackGuard_Disarm();
#if defined(FOC_RC_DEFERRED_SHADOW)
    FocRcDeferredPlan_Clear(&cl_deferred_plan);
#endif
    if (cl_session.state==CL_RUNNING) cl_stop_us=AS5047P_DmaNowUs();
    ClSession_Trip(&cl_session); cl_request=0U; cl_flags|=flags;
    if (!cl_fault_valid) {
        cl_fault_seq=cl_seq; cl_fault_u=cl_last_u; cl_fault_v=cl_last_v;
        cl_fault_last_us=cl_last_us; cl_off_us=AS5047P_DmaNowUs(); cl_fault_valid=1U;
#if defined(FOC_STARTUP_TRACE)
        /* Output closure above comes first. Preserve evidence before zeroing
         * Iq/ref or allowing later cleanup flags to obscure the first cause. */
        FocStartup_Fault(&cl_startup,flags,cl_off_us,ProtectedLoop_StartupFrame(cl_off_us));
#endif
    }
    cl_safety.protection.fault_flags|=flags;
    (void)FocFp_Trip(&cl_safety.protection,FOC_FP_HEALTH,0U);
    /* One cold binding hook replaces generic inline Trip instrumentation.
     * Outputs are already off; freeze only an open physical-pair trace. */
    FOC_TRACE_CALL(FocCurrentTrace_Protection(&cl_safety.protection));
#if defined(FOC_REPAIR_WINDOW_TRACE)
    /* Closure above must precede freezing evidence. No ring copy, printf,
     * sample retry or feedback substitution occurs on this fault path. */
    FocRepairTrace_Freeze(&cl_safety.trace,cl_safety.protection.reason,
        cl_safety.protection.repair_window,cl_safety.protection.repair_streak,
        cl_safety.protection.cfg.repair_hits_per_32,cl_safety.protection.cfg.repair_streak,
        cl_safety.protection.repaired_pairs);
#endif
    cl_frame.ready=0U;
    foc_enable=run_zero_cal_done=0U; foc_id_ref_A=foc_iq_ref_A=0.0f;
    if (!foc_fault) foc_fault_reason=9U;
    foc_fault=analog_safe_latched=1U;
    __DMB(); __set_PRIMASK(mask);
}
/* Normal STOP keeps the ADC trigger/guardian alive for diagnostics, but never
 * lets a pending task re-open the gates. Power closure precedes publication. */
FOC_RAM_PATH static void ProtectedLoop_Stop(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    FocPwmPending_Invalidate(&cl_pwm_pending);
#endif
#if defined(FOC_RC_DEFERRED_SHADOW)
    FocRcDeferredPlan_Clear(&cl_deferred_plan);
#endif
    DRIVER_SD_GPIO_Port->BSRR=(uint32_t)DRIVER_SD_Pin<<16U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE); TIM1->CCER=0U;
    __DSB();
    if (cl_session.state==CL_RUNNING) cl_stop_us=AS5047P_DmaNowUs();
#if defined(FOC_LATEST_ORIGINAL_FSM)
    if (cl_session.state==CL_RUNNING) {
        tightening_stop_request_id=0U;
        __DMB(); tightening_stop_request=1U;
    }
#endif
    ClSession_Stop(&cl_session); cl_request=0U;
#if defined(FOC_STARTUP_TRACE)
    FocStartup_Stop(&cl_startup);
#endif
    foc_id_ref_A=foc_iq_ref_A=0.0f;
    __set_PRIMASK(mask);
}
/* Explicit maintenance stop: unlike the trial STOP, also stop shadow FOC and
 * its trigger before permitting inactive-slot flash writes. No reset-to-ready. */
static void ProtectedLoop_Shutdown(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    ProtectedLoop_Stop();
    FocFeedbackGuard_OutputOff();
    cl_armed=0U; FocFeedbackGuard_Disarm(); cl_frame.ready=0U;
    foc_enable=run_zero_cal_done=0U;
    analog_safe_latched=1U;
    __DMB(); __set_PRIMASK(mask);
}
FOC_COMPACT_HELPER
#if defined(FOC_GATE_REUSE)
uint32_t ProtectedLoop_HealthCaptured(uint32_t now,uint8_t *gates)
#else
uint32_t ProtectedLoop_Health(uint32_t now)
#endif
{
    uint32_t flags=(adc_fault ? CL_BAD_ADC : 0U) |
        ((!encoder_valid ||
#if defined(FOC_GUARD_FAST_PATH)
          !FocGuard_Finite(&encoder_theta_e_pred)
#else
          !isfinite(encoder_theta_e_pred)
#endif
          ) ? CL_BAD_ENCODER : 0U) |
        ((!ProtectedLoop_TimerHealthy() || !FocAdcTiming_FastCanStart()) ? CL_BAD_TIMER : 0U) |
#if defined(FOC_GATE_REUSE)
        0U;
    *gates=ProtectedLoop_GatesMatch();
    if (!*gates) flags|=CL_BAD_OUTPUT;
#else
        (!ProtectedLoop_GatesMatch() ? CL_BAD_OUTPUT : 0U);
#endif
    if (cl_session.state==CL_RUNNING) {
        if ((uint32_t)(now-cl_session.outer_us)>CL_OUTER_DEADLINE_US) flags|=CL_OUTER_STALE;
#if defined(FOC_GUARD_FAST_PATH)
        const float speed_limit=(float)CL_OVERSPEED_RPM;
        if (!FocGuard_Within(&encoder_speed_rpm,&speed_limit)) flags|=CL_OVERSPEED;
#else
        if (!isfinite(encoder_speed_rpm) || fabsf(encoder_speed_rpm)>CL_OVERSPEED_RPM) flags|=CL_OVERSPEED;
#endif
        if (fw_update.active || !cl_boot_confirmed || !run_zero_cal_done) flags|=CL_BAD_ADMISSION;
    }
    return flags;
}
#if defined(FOC_GATE_REUSE)
FOC_COMPACT_HELPER uint32_t ProtectedLoop_Health(uint32_t now)
{
    uint8_t gates; return ProtectedLoop_HealthCaptured(now,&gates);
}
#endif
/* Fresh on every physical pair; even calibration cannot conceal a stopped or
 * repeated conversion. Calibration is performed ONLY with output registers OFF. */
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
FOC_RAM_PATH __attribute__((noinline,optimize("Os")))
static uint32_t ProtectedLoop_PwmHealth(uint32_t now)
{
    uint32_t flags=ProtectedLoop_Health(now);
    if ((uint32_t)(now-cl_last_us)>100U || cl_seq!=injected_seq_count)
        flags|=CL_BAD_ADC;
    /* Recheck independent feedback timeout BEFORE publishing the held PWM.
     * No new current classification, no threshold change or fault clear. */
    if (!flags && FocFeedbackSafety_Poll(&cl_safety,now,0U,1U)==FOC_OC_TRIPPED)
        flags|=CL_BAD_ADC;
    return flags;
}
#endif
FOC_HOT_PATH
static int ProtectedLoop_Pair(uint16_t u,uint16_t v)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (!cl_armed) { __set_PRIMASK(mask); return 0; }
    uint32_t now=AS5047P_DmaNowUs();
#if defined(FOC_GATE_REUSE)
    uint8_t gates;
    uint32_t flags=ProtectedLoop_HealthCaptured(now,&gates);
    if (ClSession_Expired(&cl_session,now)) {
        ProtectedLoop_Stop(); gates=ProtectedLoop_GatesMatch();
    }
#else
    uint32_t flags=ProtectedLoop_Health(now);
    if (ClSession_Expired(&cl_session,now)) ProtectedLoop_Stop();
#endif
    cl_last_u=u; cl_last_v=v;
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
    if (!flags && (uint32_t)(now-cl_last_us)>100U)
        FaultDiag_DirectTimeout(FOC_TO_ADC_GUARD,now,cl_last_us,100U);
#endif
    if (flags || u>4095U || v>4095U || now==cl_last_us ||
        (uint32_t)(now-cl_last_us)>100U || (uint32_t)(injected_seq_count-cl_seq)!=1U) {
        ProtectedLoop_EmergencyOff(flags ? flags : CL_BAD_ADC);
        __set_PRIMASK(mask); return 0;
    }
    cl_seq=injected_seq_count; cl_last_us=now;
    if (cl_session.state==CL_CALIBRATING) {
        FocZeroMedian_Push(&cl_zero_filter,&cl_zero,u,v);
        if (cl_zero.state==FOC_ZERO_FAILED) ProtectedLoop_EmergencyOff(CL_BAD_ZERO);
        else if (cl_zero.state==FOC_ZERO_READY) {
            iu_zero_raw=cl_zero.zero_u; iv_zero_raw=cl_zero.zero_v;
            FocFeedbackSafetyConfig cfg={
                .protection={FOC_CURRENT_TRIP_A,100U,100U,CL_REPAIR_WINDOW,CL_REPAIR_STREAK},
                .zero_u=iu_zero_raw,.zero_v=iv_zero_raw,
                .count_to_A=(float)ADC_VREF_MV/((float)ADC_FULL_SCALE*CURRENT_GAIN_MV_PER_A)};
            if (FocFeedbackSafety_Begin(&cl_safety,cfg,now)==FOC_OC_TRIPPED)
                ProtectedLoop_EmergencyOff(CL_BAD_ZERO);
            else {
                cl_session.state=CL_READY; current_filter_enable=run_zero_cal_done=foc_enable=1U;
            }
        }
        __set_PRIMASK(mask); return 0;
    }
    FOC_TRACE_CALL(FocCurrentTrace_Pending(cl_pwm_pending.valid));
    FocOcConfirmResult result=FocFeedbackSafety_Push(&cl_safety,cl_seq,now,u,v,
        encoder_theta_e_pred,flags,
#if defined(FOC_GATE_REUSE)
        /* PRIMASK excludes software STOP/state changes. Hardware break can
         * still clear MOE in RUNNING: never reuse that state's gate proof.
         * In hard-OFF with AOE=0 a break cannot open a previously closed gate. */
        cl_session.state==CL_RUNNING ? ProtectedLoop_GatesMatch() : gates);
#else
        ProtectedLoop_GatesMatch());
#endif
    int ready=0;
#if defined(FOC_FAST_CURRENT_REJECT)
    cl_current_path=cl_safety.validation.last_path;
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
    if (result!=FOC_OC_TRIPPED &&
        (cl_current_path==FOC_CURRENT_PATH_SUSPECT || cl_current_path==FOC_CURRENT_PATH_UNRESOLVED))
        ++current_hold_total;
#endif
#endif
    if (result!=FOC_OC_TRIPPED) {
#if defined(FOC_GATE_REUSE)
        /* Explicit order: read time before refreshing RUNNING hardware gates.
         * Do not rely on C's unspecified function-argument evaluation order. */
        uint32_t take_now=AS5047P_DmaNowUs();
        uint8_t take_gates=cl_session.state==CL_RUNNING ? ProtectedLoop_GatesMatch() : gates;
        ready=FocFeedbackSafety_Take(&cl_safety,take_now,flags,take_gates,&cl_frame);
#else
        ready=FocFeedbackSafety_Take(&cl_safety,AS5047P_DmaNowUs(),flags,
            ProtectedLoop_GatesMatch(),&cl_frame);
#endif
    }
    if (cl_safety.protection.result==FOC_OC_TRIPPED) ProtectedLoop_EmergencyOff(flags);
    __set_PRIMASK(mask); return ready;
}
FOC_HOT_PATH
static void ProtectedLoop_WorkEnd(uint32_t begin)
{
    uint32_t elapsed=AS5047P_DmaNowUs()-begin;
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    ++cl_work_n; if (elapsed>cl_work_max) cl_work_max=elapsed;
    if (elapsed>=50U) {
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
        FaultDiag_DirectTimeout(FOC_TO_COMPUTE_WALL,begin+elapsed,begin,50U);
#endif
        ++cl_late; ProtectedLoop_EmergencyOff(CL_COMPUTE_LATE);
#if defined(FOC_PAIR_FAST_PATH)
        if (!cl_late_cost.valid) {
            cl_late_cost=cl_frame_cost;
#if defined(FOC_IRQ_SOURCE_TRACE)
            cl_late_irq=cl_frame_irq; /* First frame only, after emergency OFF. */
#endif
            cl_late_cost.elapsed_us=elapsed;
            cl_late_cost.valid=1U;
        }
#endif
    }
    __set_PRIMASK(mask);
}
#if defined(FOC_FAST_CURRENT_REJECT)
/* Advance physical time on both valid and held cycles, never PI memory.
 * Bounded wrap replaces while-loops only in this new profile. A nonsensical
 * encoder rate is a fault, not an unbounded wrap or a frozen rotor estimate. */
FOC_HOT_INLINE void ProtectedLoop_AdvanceAngle(void)
{
    float angle=encoder_theta_e_pred+encoder_omega_e_rad_s*FOC_TS_S;
    if (!FocGuard_Finite(&angle) || angle < -TWO_PI_F || angle >= 2.0f*TWO_PI_F)
        ProtectedLoop_EmergencyOff(CL_BAD_ENCODER);
    else {
        if (angle>=TWO_PI_F) angle-=TWO_PI_F;
        if (angle<0.0f) angle+=TWO_PI_F;
        encoder_theta_e_pred=angle;
    }
}
/* Called after IrqExit from the outer ADC vector: includes entry adapter,
 * pair validation, FOC, old profiling and preemption. Exception stacking,
 * this recorder's own tail and unstacking are NOT included; retain margin.
 * A measured miss trips; profiling cannot prevent or prove absence of misses. */
FOC_HOT_PATH void ProtectedLoop_AdcProfileEnd(uint32_t start)
{
    /* Include the optional phase ledger's reducer in the EXISTING outer
     * deadline measurement; its own per-stage total stops before reduction. */
    /* Fault snapshot/abort work is not a completed healthy normal FOC frame. */
    FocProfile_End(cl_current_path==FOC_CURRENT_PATH_NORMAL && !cl_fault_valid);
#if defined(FOC_PREEMPT_COMMIT_PROBE)
    uint32_t elapsed=FocPreempt_End(start,cl_current_path);
#else
    uint32_t elapsed=DWT->CYCCNT-start;
#endif
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (FocCurrentCycles_Record(&cl_current_cycles,elapsed,cl_current_path))
        ProtectedLoop_EmergencyOff(CL_COMPUTE_LATE);
    __set_PRIMASK(mask);
}
/* Task context only. Short coherent copy, then 64-bit rate/formatting outside
 * PRIMASK. Counts cover post-calibration pairs and never reset on START. */
__attribute__((noinline,optimize("Os")))
static void ProtectedLoop_CurrentMonitor(void)
{
#if defined(FOC_PREEMPT_COMMIT_PROBE)
    FocPreempt_CheckPriorities();
    FocPreempt_Monitor();
#else
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    FocCurrentValidation s=cl_safety.validation;
    FocCurrentCycleStats c=cl_current_cycles;
    __set_PRIMASK(mask);
    char line[480];
    UART_SendFormatted(line,sizeof(line),
        "CURRENT VALIDATION samples=%lu suspect=%lu spike=%lu transition=%lu unresolved=%lu run=%lu max_unresolved_run=%lu fault=%lu recovered=%lu normal_max_cycles=%lu suspect_max_cycles=%lu unresolved_max_cycles=%lu last_cycles=%lu max_cycles=%lu deadline_miss=%lu\r\n",
        (unsigned long)s.current_samples_total,(unsigned long)s.current_suspect_total,
        (unsigned long)s.current_confirmed_spike,(unsigned long)s.current_confirmed_transition,
        (unsigned long)s.current_unresolved_total,(unsigned long)s.current_unresolved_consecutive,
        (unsigned long)s.current_unresolved_max_consecutive,
        (unsigned long)s.current_measurement_fault_count,
        (unsigned long)s.current_recovered_after_unresolved,
        (unsigned long)c.normal_max_cycles,(unsigned long)c.suspect_max_cycles,
        (unsigned long)c.unresolved_max_cycles,
        (unsigned long)c.last_cycles,(unsigned long)c.max_cycles,
        (unsigned long)c.deadline_miss_count);
#endif
}
#endif
#if defined(FOC_FAST_MATH)
#define TIM7_DAC_IRQHandler ProtectedLoop_GuardIrqBody
#endif
FOC_HOT_PATH
void TIM7_DAC_IRQHandler(void)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    /* Lower-priority health work must NOT conceal itself inside one long
     * PRIMASK section. ADC may preempt these read-only checks. If it does,
     * discard that old epoch rather than underflow now-last_sample or act on
     * a mixed health snapshot. ADC has just run the same live health checks.
     * Only the existing protection-state poll remains serialized below. */
    uint32_t sr=TIM7->SR; TIM7->SR=0U;
    if (!cl_armed) return;
    ++cl_irqs;
    uint32_t health_seq=cl_seq;
    uint32_t flags=ProtectedLoop_Health(AS5047P_DmaNowUs());
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (!cl_armed || health_seq!=cl_seq) { __set_PRIMASK(mask); return; }
    uint32_t now=AS5047P_DmaNowUs();
#else
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint32_t sr=TIM7->SR; TIM7->SR=0U;
    if (!cl_armed) { __set_PRIMASK(mask); return; }
    ++cl_irqs; uint32_t now=AS5047P_DmaNowUs();
    uint32_t flags=ProtectedLoop_Health(now);
#endif
    if (!(sr & TIM_SR_UIF) || now==cl_guard_us) flags|=CL_BAD_TIMER;
    cl_guard_us=now;
#if defined(FOC_GUARD_FAST_PATH)
    uint8_t expired=(uint8_t)ClSession_Expired(&cl_session,now);
    if (expired) ProtectedLoop_Stop();
#else
    if (ClSession_Expired(&cl_session,now)) ProtectedLoop_Stop();
#endif
    if (flags) ProtectedLoop_EmergencyOff(flags);
    else if ((uint32_t)(now-cl_last_us)>100U) {
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
        FaultDiag_DirectTimeout(FOC_TO_ADC_GUARD,now,cl_last_us,100U);
#endif
        ProtectedLoop_EmergencyOff(CL_BAD_ADC);
    }
    else if (cl_session.state!=CL_CALIBRATING &&
        FocFeedbackSafety_Poll(&cl_safety,now,0U,
#if defined(FOC_GUARD_FAST_PATH)
            /* Reuse Health only if no STOP changed the output state. An
             * expired session must recheck actual gates after closure. */
            expired ? ProtectedLoop_GatesMatch() : 1U
#else
            ProtectedLoop_GatesMatch()
#endif
            )==FOC_OC_TRIPPED)
        ProtectedLoop_EmergencyOff(0U);
    __set_PRIMASK(mask);
}
#if defined(FOC_FAST_MATH)
#undef TIM7_DAC_IRQHandler
FOC_RAM_PATH void TIM7_DAC_IRQHandler(void)
{
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreToken token=FocPreempt_IrqBegin(FOC_PRE_GUARD);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    uint32_t profile_irq_begin=DWT->CYCCNT;
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    /* A lower-priority service interval must not be counted as ADC preempt. */
    ProtectedLoop_GuardIrqBody();
#elif defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
    FocIrqSource_Enter(FOC_IRQ_GUARD); ProtectedLoop_GuardIrqBody(); FocIrqSource_Leave(FOC_IRQ_GUARD);
#else
    FocIrqLoad_Enter(); ProtectedLoop_GuardIrqBody(); FocIrqLoad_Leave();
#endif
#if defined(FOC_PREEMPT_COMMIT_PROBE) && FOC_HEAVY_PROFILE_ENABLE
    FocPreempt_IrqEnd(FOC_PRE_GUARD,token);
#endif
#if defined(FOC_FAST_PATH_PROFILE)
    FocProfile_IrqRecord(0U,profile_irq_begin);
#endif
}
#endif
#if defined(FOC_ZERO_VALID_ADMISSION)
/* Foreground only: calibration has stopped before StartupTask calls this.
 * Command callers see diagnostic snapshots; no formatting in the ADC IRQ. */
__attribute__((noinline,cold,optimize("Oz")))
static void ProtectedLoop_ZeroAdmissionFormat(char *out,size_t size)
{
    const FocZeroRobust *s=&cl_zero_filter.robust;
    uint32_t rate=s->total_count ? s->reject_count*1000U/s->total_count : 0U;
    snprintf(out,size,"OK ZERO CAL valid=%lu reject=%lu total=%lu reject_rate_ppt=%lu max_consecutive_reject=%lu zero_u=%u zero_v=%u result=%u STATE=%u REASON=%u FLAGS=%u",
        (unsigned long)cl_zero.count,(unsigned long)s->reject_count,
        (unsigned long)s->total_count,(unsigned long)rate,
        (unsigned long)s->max_consecutive_reject,cl_zero.zero_u,cl_zero.zero_v,
        cl_zero.state==FOC_ZERO_READY,cl_zero.state,cl_zero.reason,s->flags);
}
#endif
static int ProtectedLoop_Init(void)
{
    if (cl_initialized || foc_fault || adc_fault || !encoder_valid) return 0;
#if defined(FOC_FAST_CURRENT_REJECT)
    if (SystemCoreClock!=170000000U) return 0; /* 8500-cycle deadline contract. */
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;
    if (!(DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk)) return 0;
#endif
    cl_initialized=1U; analog_safe_latched=1U;
    FocFeedbackGuard_OutputOff(); FOC_ResetController(); MotorControl_SetIdle();
    /* Foreground, before sampling/guard are armed. A trial may calibrate and
     * pass the normal health gate, but only its confirmation RESET can create
     * this admission certificate. Missing/invalid metadata fails closed. */
    BootMetaV3_t boot;
    cl_boot_confirmed=(uint8_t)(BootMeta_ReadV3(&boot) &&
        boot.confirmed_slot==APP_THIS_SLOT && boot.pending_slot==BOOT_SLOT_NONE &&
        boot.attempts_left==0U);
    encoder_theta_e_pred=encoder_theta_e;
    /* StartupTask owns calibration; MotorControlTask does not exist yet.
     * Starting periodic encoder DMA here would arm its 2.5 ms consumer
     * watchdog without a consumer. Keep the checked startup angle while
     * physical output is off; start periodic acquisition in the real task. */
    if (AS5047P_DmaIsPeriodic() ||
        FocAdcTiming_Commit(0.5f,0.5f,0.5f)!=FOC_WINDOW_OK || !FocAdcTiming_CertifyClock()) return 0;
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    FocPwmPending_Init(&cl_pwm_pending,(uint16_t)TIM1->CCR1);
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
    cl_pwm_neutral_commits=0U;
#endif
#endif
    uint32_t hz=HAL_RCC_GetPCLK1Freq();
    if (RCC->CFGR & RCC_CFGR_PPRE1) hz*=2U;
    __HAL_RCC_TIM7_CLK_ENABLE();
    if (!FocFeedbackGuard_Prepare(hz)) return 0;
    cl_psc=hz/1000000U-1U;
    if (!(TIM2->CR1 & TIM_CR1_CEN) || TIM2->PSC!=cl_psc || TIM2->ARR!=UINT32_MAX) return 0;
    uint16_t nominal=analog_vdda_boot_valid && analog_vdda_boot_mv ?
        (uint16_t)((FOC_ZERO_NOMINAL_MV*ADC_FULL_SCALE+analog_vdda_boot_mv/2U)/analog_vdda_boot_mv) : 0U;
    FocZeroMedian_Begin(&cl_zero_filter,&cl_zero,nominal);
    if (cl_zero.state==FOC_ZERO_FAILED) return 0;
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    HAL_NVIC_SetPriority(TIM7_DAC_IRQn,FOC_SOFTWARE_GUARD_PRIORITY,0U);
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
    HAL_NVIC_SetPriority(ADC1_2_IRQn,2U,0U);
#else
    HAL_NVIC_SetPriority(ADC1_2_IRQn,1U,0U);
#endif
    cl_last_us=cl_guard_us=AS5047P_DmaNowUs(); cl_seq=injected_seq_count;
    cl_armed=1U; TIM1->CR1|=TIM_CR1_CEN; FocFeedbackGuard_Arm();
    __set_PRIMASK(mask);
#if defined(FOC_PREEMPT_COMMIT_PROBE)
    FocPreempt_CheckPriorities();
#endif
    uint32_t deadline=HAL_GetTick()+FOC_ZERO_TIMEOUT_MS;
    while (cl_session.state==CL_CALIBRATING && (int32_t)(HAL_GetTick()-deadline)<0)
        vTaskDelay(pdMS_TO_TICKS(1U));
#if defined(FOC_ZERO_VALID_ADMISSION)
    {
        char report[256];
        ProtectedLoop_ZeroAdmissionFormat(report,sizeof report);
        UART_SendLiteral(report); UART_SendLiteral("\r\n");
    }
#endif
    if (cl_session.state!=CL_READY) {
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
        if (cl_session.state==CL_CALIBRATING)
            FaultDiag_Capture(FOC_DIAG_STARTUP,7U,FOC_TO_STARTUP_ZERO,
                HAL_GetTick()-(deadline-FOC_ZERO_TIMEOUT_MS),FOC_ZERO_TIMEOUT_MS);
#endif
        ProtectedLoop_EmergencyOff(CL_BAD_ZERO); return 0;
    }
#if defined(FOC_LATEST_ORIGINAL_FSM)
    /* Readiness is not actuation. Explicit ANALOG SAFE/Shutdown cannot re-enter
     * this one-shot initialization. A trial must confirm/reset first. */
    if (cl_boot_confirmed) analog_safe_latched=0U;
#endif
    return 1;
}
#if defined(FOC_READY_TIMESTAMP_SNAPSHOT)
#include "protected_readiness.h"
static ProtectedReadiness cl_ready_check;
static ProtectedReadinessReject cl_ready_reject;
static uint32_t cl_ready_attempts;
#define CL_READY_REQUIRE(condition,reason) ProtectedReady_Require(&cl_ready_check,(condition),(reason))
static uint8_t ProtectedLoop_AdcReady(void)
{
    /* ADC can preempt a FreeRTOS critical section. Load its published reference
     * FIRST, then read time: never subtract a newer ISR timestamp from old now.
     * Volatile load + barrier also preserve this order in optimized firmware.
     * A delayed task may conservatively reject; there is no retry/age bypass. */
    uint32_t reference=*(volatile uint32_t *)&cl_last_us;
    __DMB();
    uint32_t now=AS5047P_DmaNowUs();
    cl_ready_check.adc_us=reference;cl_ready_check.now_us=now;
    cl_ready_check.age_us=now-reference;cl_ready_check.clock_valid=1U;
    return (uint8_t)(cl_ready_check.age_us<=100U);
}
#define CL_READY_ADC_FRESH() ProtectedLoop_AdcReady()
#endif
static uint8_t ProtectedLoop_Ready(void)
{
#if defined(FOC_READY_TIMESTAMP_SNAPSHOT)
    cl_ready_check=(ProtectedReadiness){0};
#endif
#if defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_RC_DEFERRED_SHADOW) || defined(FOC_FAST_REJECT_COMPUTE_ONLY)
    return 0U; /* Observer builds never admit motor actuation. */
#else
#if defined(FOC_READY_TIMESTAMP_SNAPSHOT)
    return CL_READY_REQUIRE(cl_session.state==CL_READY,CL_READY_STATE) &&
        CL_READY_REQUIRE(!cl_session.used,CL_READY_USED) && CL_READY_REQUIRE(cl_armed,CL_READY_ARMED) &&
        CL_READY_REQUIRE(!cl_request,CL_READY_REQUEST) && CL_READY_REQUIRE(!adc_fault,CL_READY_ADC_FAULT) &&
        CL_READY_REQUIRE(!foc_fault,CL_READY_FOC_FAULT) && CL_READY_REQUIRE(run_zero_cal_done,CL_READY_ZERO) &&
        CL_READY_REQUIRE(!fw_update.active,CL_READY_UPDATE) && CL_READY_REQUIRE(cl_boot_confirmed,CL_READY_BOOT) &&
        CL_READY_REQUIRE(UART_Async_IsReady(),CL_READY_UART) &&
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
        CL_READY_REQUIRE(ProtectedLoop_PwmNeutralReady(),CL_READY_PWM) &&
#elif defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
        CL_READY_REQUIRE(FocAdcTiming_RcActuationReady(),CL_READY_PWM) &&
#endif
        CL_READY_REQUIRE(cl_work_n,CL_READY_WORK) && CL_READY_REQUIRE(cl_outer_n,CL_READY_OUTER) &&
        CL_READY_REQUIRE(AS5047P_DmaIsPeriodic(),CL_READY_PERIODIC) &&
        CL_READY_REQUIRE(cl_safety.protection.result==FOC_OC_CLEAR,CL_READY_CURRENT) &&
        CL_READY_REQUIRE(ProtectedLoop_TimerHealthy(),CL_READY_TIMER) &&
        CL_READY_REQUIRE(ProtectedLoop_GatesMatch(),CL_READY_GATES) &&
        CL_READY_REQUIRE(CL_READY_ADC_FRESH(),CL_READY_ADC_AGE) &&
        CL_READY_REQUIRE(encoder_valid,CL_READY_ENCODER) &&
        CL_READY_REQUIRE(isfinite(encoder_speed_rpm) && fabsf(encoder_speed_rpm)<=2.0f,CL_READY_SPEED) &&
        CL_READY_REQUIRE(motor_control_mode==MOTOR_MODE_IDLE,CL_READY_MODE) &&
#if defined(FOC_INTENT_FSM_CANDIDATE)
        /* PRECHECK is logically busy to UART/recipe writers, but has not
         * admitted or commanded motion. All other existing readiness gates
         * above remain mandatory; no RUNNING/TIGHTEN state can use this. */
        CL_READY_REQUIRE((!Tightening_IsBusy() || TighteningIntent_PrecheckOnly()),CL_READY_BUSY) &&
#else
        CL_READY_REQUIRE(!Tightening_IsBusy(),CL_READY_BUSY) &&
#endif
        CL_READY_REQUIRE(!tightening_start_request,CL_READY_START);
#else
    /* Existing profiles, including B, keep their exact historical expression. */
    return cl_session.state==CL_READY && !cl_session.used && cl_armed &&
        !cl_request && !adc_fault && !foc_fault && run_zero_cal_done &&
        !fw_update.active && cl_boot_confirmed && UART_Async_IsReady() &&
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
        ProtectedLoop_PwmNeutralReady() &&
#elif defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
        FocAdcTiming_RcActuationReady() &&
#endif
        cl_work_n && cl_outer_n && AS5047P_DmaIsPeriodic() &&
        cl_safety.protection.result==FOC_OC_CLEAR &&
        ProtectedLoop_TimerHealthy() && ProtectedLoop_GatesMatch() &&
        (uint32_t)(AS5047P_DmaNowUs()-cl_last_us)<=100U &&
        encoder_valid && isfinite(encoder_speed_rpm) && fabsf(encoder_speed_rpm)<=2.0f &&
        motor_control_mode==MOTOR_MODE_IDLE &&
#if defined(FOC_INTENT_FSM_CANDIDATE)
        (!Tightening_IsBusy() || TighteningIntent_PrecheckOnly()) &&
#else
        !Tightening_IsBusy() &&
#endif
        !tightening_start_request;
#endif
#endif
}
#if defined(FOC_MECHANICAL_DOB_SHADOW)
#include "mechanical_dob_binding.inc"
#if defined(FOC_ID_STEADY_STATS)
#include "id_steady_binding.inc"
#endif
#endif
FOC_RAM_PATH static void ProtectedLoop_SetDuty(float du,float dv,float dw)
{
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    ProtectedLoop_PwmStage(du,dv,dw);
#elif defined(FOC_PREEMPT_COMMIT_PROBE)
    /* Legacy profile is hypothetical only after removal of the intrusive
     * UDIS transaction. Real commits require OneCyclePwmPipeline above. */
    DRIVER_SD_GPIO_Port->BSRR=(uint32_t)DRIVER_SD_Pin<<16U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    TIM1->CCER=0U;
    __DSB();
    FocAdcTiming_ProfileDutyPoint();
    (void)du; (void)dv; (void)dw;
#elif defined(FOC_RC_DEFERRED_SHADOW)
    /* Observe an actual FOC-produced plan while output is locked. Never
     * publish this plan to CCR or admit motor control from the observer. */
    if (cl_session.state!=CL_READY || !cl_armed || adc_fault || foc_fault) {
        FocRcDeferredPlan_Clear(&cl_deferred_plan);
        return;
    }
    FocWindowPlan plan;
    FocWindowStatus status=FocAdcTiming_Prepare(du,dv,dw,&plan);
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (status!=FOC_WINDOW_OK || cl_session.state!=CL_READY || !cl_armed ||
        adc_fault || foc_fault || !ProtectedLoop_GatesMatch()) {
        ++cl_deferred_plan_fail;
        FocRcDeferredPlan_Clear(&cl_deferred_plan);
    } else {
        FocRcPlanResult result=FocRcDeferredPlan_Stage(&cl_deferred_plan,cl_seq,&plan);
        if (result==FOC_RC_PLAN_READY) ++cl_deferred_staged;
        else ++cl_deferred_rejected;
    }
    __set_PRIMASK(mask);
#elif defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_FAST_REJECT_COMPUTE_ONLY)
    (void)du; (void)dv; (void)dw;
    /* Shadow FOC must keep its ADC-only TIM1 trigger alive. EmergencyOff /
     * Shutdown still stop CEN; this path never starts/restarts the timer. */
    DRIVER_SD_GPIO_Port->BSRR=(uint32_t)DRIVER_SD_Pin<<16U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    TIM1->CCER=0U;
    __DSB();
#if defined(FOC_FAST_PATH_PROFILE)
    FocAdcTiming_ProfileDutyPoint();
#endif
#else
    /* This is only an early rejection, never an admission decision. The ADC
     * ISR cannot be admitted by a lower-priority task while it is executing;
     * TIM7/STOP may still revoke RUNNING and must be rechecked after planning.
     * READY/shadow computation must not spend its deadline on an unused plan. */
    if (cl_session.state!=CL_RUNNING || !cl_armed || adc_fault || foc_fault) return;
    FocWindowPlan plan;
    FocWindowStatus status=FocAdcTiming_Prepare(du,dv,dw,&plan);
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    /* TIM7/STOP can interrupt planning. Never publish a late command after
     * it has revoked the running session, even when the plan itself is OK. */
    if (cl_session.state==CL_RUNNING && cl_armed && !adc_fault && !foc_fault) {
        if (status!=FOC_WINDOW_OK) {
            FocAdcTiming_PlanFailed(status);
            ProtectedLoop_EmergencyOff(CL_BAD_ADC);
        }
#if defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
        else if (!FocAdcTiming_CommitBeforeBottom(&plan))
            ProtectedLoop_EmergencyOff(CL_COMPUTE_LATE);
#else
        else FocAdcTiming_CommitPrepared(&plan);
#endif
    }
    __set_PRIMASK(mask);
#endif
}
#if defined(FOC_RC_DEFERRED_SHADOW)
FOC_RAM_PATH static void ProtectedLoop_DeferredProbe(void)
{
    FocWindowPlan plan;
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint8_t safe=(uint8_t)(cl_session.state==CL_READY && cl_armed &&
        !adc_fault && !foc_fault && ProtectedLoop_GatesMatch() &&
        FocAdcTiming_FastCanStart());
    FocRcPlanResult result=FocRcDeferredPlan_Take(&cl_deferred_plan,cl_seq,safe,&plan);
    if (result==FOC_RC_PLAN_READY) ++cl_deferred_taken;
    else if (result==FOC_RC_PLAN_EMPTY) ++cl_deferred_empty;
    else if (result==FOC_RC_PLAN_STALE) ++cl_deferred_stale;
    else ++cl_deferred_unsafe;
    __set_PRIMASK(mask);
    /* The plan is deliberately discarded. Current-cycle ADC data must never
     * authorize a physical write, and a stale plan must never be reused. */
    (void)plan;
}
#endif
/* Actual 1 kHz task owns original speed PI and command consumption. */
static void ProtectedLoop_TaskService(void)
{
#if defined(FOC_DOB_NORMAL_CONTROL)
    DobNormal_Lifecycle(&mechanical_dob_monitor,&dob_feedback,
        (uint8_t)(cl_armed&&cl_session.state==CL_RUNNING&&motor_control_mode==MOTOR_MODE_SPEED),
        (uint8_t)(adc_fault||foc_fault));
#else
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
    if(!cl_armed||cl_session.state!=CL_RUNNING||adc_fault||foc_fault||motor_control_mode!=MOTOR_MODE_SPEED)
        DobFeedback_Clear(&dob_feedback);
#endif
#if defined(FOC_MECHANICAL_DOB_SHADOW)
    /* Evidence lifecycle only; never refreshes a watchdog or changes control. */
#if defined(FOC_DOB_ID_TRACE)
    DobIdTrace_Bind(mechanical_capture.points,sizeof mechanical_capture.points);
    mechanical_capture.flags=0x80000000U; /* Trace bytes, NEVER mechanical fit bins. */
    DobIdTrace_Lifecycle((uint8_t)(cl_armed&&cl_session.state==CL_RUNNING),(uint8_t)(adc_fault||foc_fault));
#endif
    MechanicalDobMonitor_Lifecycle(&mechanical_dob_monitor,
        (uint8_t)(cl_armed && cl_session.state==CL_RUNNING),(uint8_t)(adc_fault || foc_fault));
#if defined(FOC_ID_STEADY_STATS)
    IdSteady_Lifecycle(&id_steady_stats,(uint8_t)(cl_armed && cl_session.state==CL_RUNNING),
        (uint8_t)(adc_fault || foc_fault));
#endif
#endif
#endif /* Normal DOB lifecycle / single-use diagnostic lifecycle. */
#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
    OuterTrace_Enter(&outer_completion_trace,AS5047P_DmaNowUs(),(uint8_t)(adc_fault || foc_fault));
#endif
    if (!cl_armed) {
        MotorControl_SetIdle(); foc_iq_ref_A=0.0f;
        if (AS5047P_DmaIsPeriodic()) AS5047P_DmaStopPeriodic();
        return;
    }
    if (!AS5047P_DmaIsPeriodic()) {
        /* The sole outer-loop owner starts its own watchdog. A driver fault
         * disarms cl_armed first, so this is not an automatic fault restart. */
        if (adc_fault || foc_fault || !AS5047P_DmaStartPeriodic())
            ProtectedLoop_EmergencyOff(CL_BAD_ENCODER);
        return;
    }
    HAL_StatusTypeDef update=FOC_EncoderSpeedUpdate(0.001f);
#if defined(FOC_STARTUP_TRACE)
    /* A guard/DMA fault may preempt the outer update. Its closure already
     * disarmed us: do not relabel that completed trip as a new encoder fault. */
    if (!cl_armed) return;
#endif
    if (update==HAL_OK) { cl_session.outer_us=AS5047P_DmaNowUs(); ++cl_outer_n; }
#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
    outer_completion_trace.current.status=(uint32_t)update;
    if (update==HAL_OK && cl_armed && !adc_fault && !foc_fault) {
        OuterTrace_Commit(&outer_completion_trace,cl_session.outer_us);
        OuterTrace_ObserveBegin(&outer_completion_trace,AS5047P_DmaNowUs());
        OuterObservation_Flush();
        OuterTrace_ObserveEnd(&outer_completion_trace,AS5047P_DmaNowUs());
    } else outer_observation.pending=0U;
#endif
    if (adc_fault || foc_fault || (update!=HAL_OK && update!=HAL_BUSY)) {
        ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); return;
    }
    /* A producer/task phase boundary can expose the preceding snapshot.
     * BUSY means no accepted new sample, not a fresh heartbeat. Never refresh
     * either watchdog or admit a request from it; the independent deadlines
     * still cut off a stalled producer or stalled outer loop. */
    if (update==HAL_BUSY) return;
#if defined(FOC_STARTUP_TRACE)
    ProtectedLoop_StartupPush();
#endif
#if defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_RC_DEFERRED_SHADOW) || defined(FOC_FAST_REJECT_COMPUTE_ONLY)
    /* Compile out the ONLY bridge-enable transaction, even if a stale or
     * corrupted request/session bypasses command admission. */
    if (cl_request || cl_session.state==CL_RUNNING)
        ProtectedLoop_EmergencyOff(CL_BAD_ADMISSION);
    MotorControl_SetIdle(); foc_iq_ref_A=0.0f;
#elif defined(FOC_LATEST_ORIGINAL_FSM)
    /* The original TighteningTask owns setpoints and transitions. This task
     * owns only encoder/outer PI service; never substitutes a test-speed FSM. */
    if (cl_session.state!=CL_RUNNING) { MotorControl_SetIdle(); foc_iq_ref_A=0.0f; }
#else
    /* Planning is preemptible. A guard/STOP may revoke admission while it
     * runs; the short masked transaction below must recheck all gates. */
    FocWindowPlan admission_plan;
    FocWindowStatus admission_status=FOC_WINDOW_BAD_ARGUMENT;
    if (cl_request) admission_status=FocAdcTiming_Prepare(0.5f,0.5f,0.5f,&admission_plan);
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (cl_request) {
        cl_request=0U;
        uint8_t healthy=cl_session.state==CL_READY && cl_armed && run_zero_cal_done &&
            !adc_fault && !foc_fault && cl_outer_n && AS5047P_DmaIsPeriodic() &&
            !fw_update.active && cl_boot_confirmed && UART_Async_IsReady() &&
            ProtectedLoop_TimerHealthy() && FocAdcTiming_FastCanStart() && ProtectedLoop_GatesMatch() &&
            cl_safety.protection.result==FOC_OC_CLEAR &&
            (uint32_t)(AS5047P_DmaNowUs()-cl_last_us)<=100U &&
            isfinite(encoder_speed_rpm) && fabsf(encoder_speed_rpm)<=2.0f &&
            motor_control_mode==MOTOR_MODE_IDLE && !Tightening_IsBusy();
        if (!healthy || admission_status!=FOC_WINDOW_OK ||
            !ClSession_Start(&cl_session,AS5047P_DmaNowUs(),healthy)) {
            if (admission_status!=FOC_WINDOW_OK) FocAdcTiming_PlanFailed(admission_status);
            ProtectedLoop_EmergencyOff(CL_BAD_ADMISSION);
        } else {
            FocAdcTiming_CommitPrepared(&admission_plan);
            /* Session and timer lease published BEFORE the only power enable.
             * TIM7 can preempt normal code but never this bounded write group. */
            foc_id_ref_A=foc_iq_ref_A=0.0f; MotorControl_SetSpeed((float)CL_SPEED_RPM);
            TIM1->CCER=0x555U; TIM1->BDTR=(TIM1->BDTR & ~TIM_BDTR_AOE)|TIM_BDTR_MOE;
            DRIVER_SD_GPIO_Port->BSRR=DRIVER_SD_Pin; __DSB();
        }
    }
    if (cl_session.state!=CL_RUNNING) { MotorControl_SetIdle(); foc_iq_ref_A=0.0f; }
    __set_PRIMASK(mask);
#endif
}
#if defined(FOC_FAST_CURRENT_REJECT)
/* Cold task-only formatter. Keep the O2 realtime chain and original Flash
 * partition; there is no benefit to expanding this command dispatcher. */
__attribute__((optimize("Os")))
#endif
static void ProtectedLoop_Command(const char *cmd,char *out,size_t size)
{
#if defined(FOC_DOB_NORMAL_CONTROL)
    if (MechanicalDob_Command(cmd,out,size)) return;
#endif
#if defined(FOC_PSI_IDENT_DIAG)
    if (PsiIdent_Command(cmd,out,size)) return;
#endif
#if defined(FOC_CURRENT_STEP_AB_DIAG)
    if(CurrentStep_Command(cmd,out,size))return;
#endif
#if defined(FOC_MOTOR_IDENTIFICATION_DIAG)
    if (MotorIdent_Command(cmd,out,size)) return;
#endif
#if defined(FOC_FRICTION_CALIBRATION_DIAG)
    if (FrictionCalibration_Command(cmd,out,size)) return;
#endif
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
    if (SpeedFriction_Command(cmd,out,size)) return;
#endif
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
    if (SpeedAccelFf_Command(cmd,out,size)) return;
#endif
#if defined(FOC_TORQUE_CHAIN_DIAG)
    if (TorqueChain_Command(cmd,out,size)) return;
#endif
#if defined(FOC_REPAIR_WINDOW_TRACE)
    /* Freeze publication happens in the serialized output-off path. Once
     * frozen no ISR/command can mutate the ring until next boot/Begin. Only
     * copy the flag under mask, never format a UART line with IRQs masked. */
    if (!strncmp(cmd,"MOTOR TEST REPAIR",17U)) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint8_t frozen=cl_safety.trace.frozen;
        __DMB(); __set_PRIMASK(mask);
        if (!frozen) { snprintf(out,size,"OK REPAIR ENABLED=1 HARD_OFF=1 N=32 FROZEN=0"); return; }
        if (FocRepairTrace_Format(&cl_safety.trace,cmd,out,size)) return;
    }
#endif
#if defined(FOC_STARTUP_TRACE)
    if (ProtectedLoop_StartupCommand(cmd,out,size)) return;
#endif
#if defined(FOC_FAST_CURRENT_REJECT)
    if (!strcmp(cmd,"MOTOR TEST PROFILE")) {
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=PROTECTED_PIPELINE_CLOSED_LOOP HARD_OFF=0 FSM=ORIGINAL PIPELINE=1 LOCAL=1 RPM=" CL_SPEED_TEXT " LEASE_US=" CL_LEASE_TEXT
#if defined(FOC_PWM_COMMON_MODE_ENABLE)
            " CM=85" /* Common-mode enabled, additional reserve in TIM1 ticks. */
#endif
#if defined(FOC_SPEED_STARTUP_BRAKE)
#if defined(FOC_SPEED_BUMPLESS)
#if defined(FOC_SPEED_BRAKE_TRACK)
#if defined(FOC_SPEED_PI_ANTI_WINDUP)
#if defined(FOC_SPEED_SB3_DISABLE_CANDIDATE)
#if defined(FOC_SPEED_SCURVE_CANDIDATE)
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
            " SPEED_CTRL=FR1" /* FF/FRIC runtime switches reported separately. */
#else
            " SPEED_CTRL=AF1" /* FF default/config checked by MOTOR TEST FF STATUS. */
#endif
#else
            " SPEED_CTRL=SC1" /* AW on, SB3 off, SPEED-only S-curve reference. */
#endif
#else
            " SPEED_CTRL=AW0" /* AW1 integral admission, SB3 ceiling omitted. */
#endif
#else
            " SPEED_CTRL=AW1" /* SB3 retained; same-length protocol marker. */
#endif
#else
#if defined(FOC_SPEED_LEGACY_AW_COMPARE)
            " SPEED_CTRL=L00" /* Historical conditional integration, no SB3. */
#else
            " SPEED_CTRL=SB3"
#endif
#endif
#else
            " SPEED_CTRL=SB2"
#endif
#if defined(FOC_VOLTAGE_X2_TRIAL)
            " VLIMIT_MV=1600 ILIMIT_MV=750"
#endif
#else
            " SPEED_CTRL=SB1"
#endif
#endif
            " QUALIFIED=0"); return;
#else
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=FAST_CURRENT_REJECT HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT " FSM=ORIGINAL QUALIFIED=0"); return;
#endif
    }
    if (!strcmp(cmd,"MOTOR TEST FILTER")) {
        snprintf(out,size,"OK MOTOR TEST FILTER FAST_REJECT=1 REPAIR=0 METHOD=TWO_SAMPLE JUMP=%u RETURN=%u CONFIRM=%u UNRESOLVED_LIMIT=%u HOLD=1",
            FOC_CURRENT_JUMP_THRESHOLD_COUNTS,FOC_CURRENT_RETURN_TOL_COUNTS,
            FOC_CURRENT_CONFIRM_TOL_COUNTS,FOC_CURRENT_UNRESOLVED_LIMIT); return;
    }
    if (!strcmp(cmd,"MOTOR TEST PROTECTION")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        FocFilteredProtection p=cl_safety.protection;
        __set_PRIMASK(mask);
        snprintf(out,size,"OK MOTOR TEST PROTECTION FILTER=NONE OC=RAW_CONFIRM_4 TRIP_MA=4000 STATE=%u REASON=%u FLAGS=%lu RAW_N=%lu FEEDBACK_N=%lu",
            p.result,p.reason,(unsigned long)p.fault_flags,
            (unsigned long)p.raw_pairs,(unsigned long)p.feedback_pairs); return;
    }
#endif
#if defined(FOC_PWM_BOUNDARY_LITE)
    if (!strcmp(cmd,"MOTOR TEST PROFILE")) {
#if defined(FOC_RC_DEFERRED_SHADOW)
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=RC_DEFERRED_SHADOW HARD_OFF=0 ADMISSION=0 FSM=ORIGINAL QUALIFIED=0"); return;
#else
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=RC_BOUNDARY_LITE HARD_OFF=0 ADMISSION=0 FSM=ORIGINAL QUALIFIED=0"); return;
#endif
    }
#elif defined(FOC_PWM_BOUNDARY_TRACE)
    if (!strcmp(cmd,"MOTOR TEST PROFILE")) {
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=RC_BOUNDARY_TRACE HARD_OFF=0 ADMISSION=0 FSM=ORIGINAL QUALIFIED=0"); return;
    }
#elif defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
    if (!strcmp(cmd,"MOTOR TEST PROFILE")) {
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=RC_PROTECTED_CANDIDATE HARD_OFF=0 ADAPT=1 FSM=ORIGINAL LOCAL=1 RPM=20 LEASE_US=400000 QUALIFIED=0"); return;
    }
#elif defined(FOC_LATEST_ORIGINAL_FSM)
    if (!strcmp(cmd,"MOTOR TEST PROFILE")) {
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=LATEST_ORIGINAL_FSM HARD_OFF=0 ADAPT=1 FSM=ORIGINAL ZERO=BOUNDED LOCAL=1 RPM=20 LEASE_US=400000 QUALIFIED=0"); return;
    }
#endif
#if defined(FOC_RC_DEFERRED_SHADOW)
    if (!strcmp(cmd,"MOTOR TEST DEFERRED")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint32_t staged=cl_deferred_staged,taken=cl_deferred_taken;
        uint32_t empty=cl_deferred_empty,stale=cl_deferred_stale;
        uint32_t unsafe=cl_deferred_unsafe,rejected=cl_deferred_rejected;
        uint32_t plan_fail=cl_deferred_plan_fail;
        uint8_t valid=cl_deferred_plan.valid;
        __set_PRIMASK(mask);
        snprintf(out,size,"OK MOTOR TEST DEFERRED SHADOW=1 ADMISSION=0 PUBLISH=0 STAGED=%lu TAKEN=%lu EMPTY=%lu STALE=%lu UNSAFE=%lu REJECTED=%lu PLAN_FAIL=%lu VALID=%u",
            (unsigned long)staged,(unsigned long)taken,(unsigned long)empty,
            (unsigned long)stale,(unsigned long)unsafe,(unsigned long)rejected,
            (unsigned long)plan_fail,valid);
        return;
    }
#endif
#if defined(FOC_COMPACT_CLOSED_LOOP)
    if (!strcmp(cmd,"MOTOR TEST PROFILE")) {
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=COMPACT_CLOSED_LOOP HARD_OFF=0 ADAPT=0 ZERO=BOUNDED LOCAL=1 RPM=20 LEASE_US=400000 QUALIFIED=0"); return;
    }
#endif
#if defined(FOC_RAM_HOT_PATH)
    if (!strcmp(cmd,"MOTOR TEST RAM")) {
        snprintf(out,size,"OK MOTOR TEST RAM ENABLED=1 HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT " DEADLINE_US=50"); return;
    }
#endif
#if defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_LATEST_ORIGINAL_FSM)
#if !defined(FOC_FAST_CURRENT_REJECT)
    if (!strcmp(cmd,"MOTOR TEST FILTER")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        FocAdaptiveNoise u=cl_safety.filter.noise[0],v=cl_safety.filter.noise[1];
        __set_PRIMASK(mask);
        snprintf(out,size,"OK MOTOR TEST FILTER ADAPT=1 HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT " DELAY_PAIRS=1 JUMP=%u,%u NOISE_Q8=%u,%u LEARNED=%lu,%lu",
            FocAdaptive_Jump(&u),FocAdaptive_Jump(&v),u.noise_q8,v.noise_q8,
            (unsigned long)u.learned,(unsigned long)v.learned); return;
    }
#endif
#if defined(FOC_ZERO_ALL_REJECTED_DIAG)
    if (!strcmp(cmd,"MOTOR TEST ZERO POLICY")) {
        snprintf(out,size,"OK ZERO POLICY DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V"); return;
    }
#endif
    if (!strcmp(cmd,"MOTOR TEST ZERO ROBUST")) {
#if defined(FOC_ZERO_VALID_ADMISSION)
        ProtectedLoop_ZeroAdmissionFormat(out,size); return;
#else
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint32_t n=cl_zero_filter.robust.outliers,seg=cl_zero_filter.robust.segments;
        uint32_t seg_outliers=cl_zero_filter.robust.segment_outliers;
        uint16_t flags=cl_zero_filter.robust.flags;
        __set_PRIMASK(mask);
#if defined(FOC_ZERO_TOTAL_BUDGET_OFF) || defined(FOC_LATEST_ZERO_COUNT_ONLY)
        snprintf(out,size,"OK MOTOR TEST ZERO ROBUST BLOCK=5 SEGMENT=500 SEGMENTS=%lu OUTLIERS=%lu MAX=OFF SEG_MAX=OFF SEG_OUTLIERS=%lu FLAGS=%u HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT,
#else
        snprintf(out,size,"OK MOTOR TEST ZERO ROBUST BLOCK=5 SEGMENT=500 SEGMENTS=%lu OUTLIERS=%lu MAX=20 SEG_MAX=OFF SEG_OUTLIERS=%lu FLAGS=%u HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT,
#endif
            (unsigned long)seg,(unsigned long)n,(unsigned long)seg_outliers,flags); return;
#endif
    }
#endif
#if defined(FOC_IRQ_SOURCE_TRACE)
    if (!strcmp(cmd,"MOTOR TEST IRQ")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        FocIrqSourceFrame irq=cl_late_irq;
        uint32_t seq=cl_late_cost.seq; uint8_t valid=cl_late_cost.valid;
        __set_PRIMASK(mask);
        snprintf(out,size,"OK MOTOR TEST IRQ ORDER=G,T,R,X BODY=EXCL VALID=%u SEQ=%lu ERR=%lu CYC=%lu,%lu,%lu,%lu CNT=%lu,%lu,%lu,%lu",
            valid,(unsigned long)seq,(unsigned long)irq.error,
            (unsigned long)irq.cycles[0],(unsigned long)irq.cycles[1],
            (unsigned long)irq.cycles[2],(unsigned long)irq.cycles[3],
            (unsigned long)irq.calls[0],(unsigned long)irq.calls[1],
            (unsigned long)irq.calls[2],(unsigned long)irq.calls[3]); return;
    }
    if (!strcmp(cmd,"MOTOR TEST IRQ STATS")) {
        FocIrqSourceStats irq; FocIrqSource_Stats(&irq);
        snprintf(out,size,"OK MOTOR TEST IRQ STATS ORDER=G,T,R,X MAX=BODY_INCL ERR=%lu CNT=%lu,%lu,%lu,%lu MAX_CYC=%lu,%lu,%lu,%lu",
            (unsigned long)irq.error,
            (unsigned long)irq.calls[0],(unsigned long)irq.calls[1],
            (unsigned long)irq.calls[2],(unsigned long)irq.calls[3],
            (unsigned long)irq.max_inclusive[0],(unsigned long)irq.max_inclusive[1],
            (unsigned long)irq.max_inclusive[2],(unsigned long)irq.max_inclusive[3]); return;
    }
    if (!strcmp(cmd,"MOTOR TEST IRQ TOTAL")) {
        FocIrqSourceStats irq; FocIrqSource_Stats(&irq);
        snprintf(out,size,"OK MOTOR TEST IRQ TOTAL ORDER=G,T,R,X BODY=EXCL ERR=%lu CYC=%lu,%lu,%lu,%lu",
            (unsigned long)irq.error,(unsigned long)irq.cycles[0],(unsigned long)irq.cycles[1],
            (unsigned long)irq.cycles[2],(unsigned long)irq.cycles[3]); return;
    }
#endif
    if (!strcmp(cmd,"MOTOR TEST STOP") || !strcmp(cmd,"STOP")) {
        ProtectedLoop_Stop(); snprintf(out,size,"OK MOTOR TEST STOP OUTPUT_OFF=1"); return;
    }
    if (!strcmp(cmd,"MOTOR TEST SPEED")) {
#if defined(FOC_LATEST_ORIGINAL_FSM)
        snprintf(out,size,"ERR 109 USE_ORIGINAL_START"); return;
#else
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        int accepted=ClSession_Queue(&cl_session,ProtectedLoop_Ready());
        if (accepted) { __DMB(); cl_request=1U; }
        __set_PRIMASK(mask);
        snprintf(out,size,accepted ? "OK MOTOR TEST QUEUED=1 RPM=20 MAX_US=400000" : "ERR 109 MOTOR_TEST_REJECTED"); return;
#endif
    }
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    ClSession s=cl_session; FocFilteredProtection p=cl_safety.protection;
    FocZeroCal z=cl_zero;
    uint32_t elapsed=!s.started ? 0U : s.state==CL_RUNNING ? AS5047P_DmaNowUs()-s.start_us : cl_stop_us-s.start_us;
    uint32_t work=cl_work_n,max=cl_work_max,irqs=cl_irqs,outer=cl_outer_n,late=cl_late,flags=cl_flags;
    uint8_t armed=cl_armed,fault=cl_fault_valid;
    uint32_t fault_seq=cl_fault_seq,last=cl_fault_last_us,off=cl_off_us;
#if defined(FOC_FAST_MATH)
    uint32_t cpu_max=cl_cpu_max_cyc,preempt_max=cl_preempt_max_cyc;
    uint32_t pair_max=cl_pair_max_us,math_max=cl_math_max_us;
#endif
#if defined(FOC_PAIR_FAST_PATH)
    FocFrameCost first_late=cl_late_cost;
#endif
    uint16_t raw_u=cl_fault_u,raw_v=cl_fault_v;
    __set_PRIMASK(mask);
    if (!strcmp(cmd,"MOTOR TEST STATUS"))
        snprintf(out,size,"OK MOTOR TEST STATE=%u USED=%u QUEUED=%u ARMED=%u US=%lu ZERO=%u FLAGS=%lu FAULT=%u SD=%u MOE=%u CCER=%lX QUALIFIED=0",
            s.state,s.used,s.queued,armed,(unsigned long)elapsed,z.state,(unsigned long)flags,fault,
            (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin)!=0U,(TIM1->BDTR & TIM_BDTR_MOE)!=0U,(unsigned long)TIM1->CCER);
    else if (!strcmp(cmd,"MOTOR TEST ZERO"))
#if defined(FOC_ZERO_VALID_ADMISSION)
        ProtectedLoop_ZeroAdmissionFormat(out,size);
#else
        snprintf(out,size,"OK MOTOR TEST ZERO STATE=%u REASON=%u NOM=%u U0=%u V0=%u N=%lu RET=%lu RNG=%u:%u,%u:%u RAW_STATE=%u RAW_REASON=%u",
            z.state,z.reason,z.nominal,z.zero_u,z.zero_v,(unsigned long)z.count,(unsigned long)z.restarts,
            z.min_u,z.max_u,z.min_v,z.max_v,cl_zero_filter.raw.state,cl_zero_filter.raw.reason);
#endif
#if !defined(FOC_FAST_CURRENT_REJECT)
    else if (!strcmp(cmd,"MOTOR TEST PROTECTION"))
        snprintf(out,size,"OK MOTOR TEST PROTECTION FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000 STATE=%u REASON=%u FLAGS=%lu REPAIRED=%lu BUDGET=6 STREAK=4 RAW_N=%lu FEEDBACK_N=%lu",
            p.result,p.reason,(unsigned long)p.fault_flags,(unsigned long)p.repaired_pairs,
            (unsigned long)p.raw_pairs,(unsigned long)p.feedback_pairs);
    else if (!strcmp(cmd,"MOTOR TEST REPAIR SNAP"))
        /* p and fault_seq were copied under the same mask above. The repair
         * window freezes on a trip because FocFp_Push stops accepting pairs.
         * Formatting runs in task context; there is no new ADC ISR work. */
        snprintf(out,size,"OK MOTOR TEST REPAIR SNAP STATE=%u REASON=%u SEQ=%lu WIN=0x%08lX HITS=%u RUN=%u MAX_HITS=%u MAX_RUN=%u TOTAL=%lu",
            p.result,p.reason,(unsigned long)fault_seq,(unsigned long)p.repair_window,
            FocFp_Popcount(p.repair_window),p.repair_streak,
            p.cfg.repair_hits_per_32,p.cfg.repair_streak,
            (unsigned long)p.repaired_pairs);
#endif
#if defined(FOC_IRQ_COMPACT)
    else if (!strcmp(cmd,"MOTOR TEST COMPACT"))
        snprintf(out,size,"OK MOTOR TEST COMPACT ENABLED=1 HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT " FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50");
#endif
    else if (!strcmp(cmd,"MOTOR TEST TIMING"))
        snprintf(out,size,"OK MOTOR TEST TIMING CLOCK_HZ=1000000 WORK=%lu MAX_US=%lu LATE=%lu IRQ=%lu OUTER=%lu LEASE_US=" CL_LEASE_TEXT " SAMPLE_US=100 OUTER_US=2000",
            (unsigned long)work,(unsigned long)max,(unsigned long)late,(unsigned long)irqs,(unsigned long)outer);
#if defined(FOC_FAST_MATH)
    else if (!strcmp(cmd,"MOTOR TEST COST"))
        snprintf(out,size,"OK MOTOR TEST COST TRIG=POLY9_8 DWT=%u CPU_MAX_CYC=%lu PREEMPT_MAX_CYC=%lu PAIR_MAX_US=%lu MATH_MAX_US=%lu",
            (DWT->CTRL & DWT_CTRL_CYCCNTENA_Msk)!=0U,
            (unsigned long)cpu_max,(unsigned long)preempt_max,
            (unsigned long)pair_max,(unsigned long)math_max);
#endif
#if defined(FOC_PAIR_FAST_PATH)
    else if (!strcmp(cmd,"MOTOR TEST LATE"))
        snprintf(out,size,"OK MOTOR TEST LATE PATH=PAIR2 VALID=%u SEQ=%lu US=%lu PAIR_US=%lu MATH_US=%lu WALL_CYC=%lu IRQ_CYC=%lu",
            first_late.valid,(unsigned long)first_late.seq,(unsigned long)first_late.elapsed_us,
            (unsigned long)first_late.pair_us,(unsigned long)first_late.math_us,
            (unsigned long)first_late.wall_cyc,(unsigned long)first_late.irq_cyc);
#endif
    else if (!strcmp(cmd,"MOTOR TEST FAULT"))
        snprintf(out,size,"OK MOTOR TEST FAULT VALID=%u REASON=%u FLAGS=%lu SEQ=%lu RAW=%u,%u LAST_VALID_US=%lu OFF_US=%lu",
            fault,p.reason,(unsigned long)flags,(unsigned long)fault_seq,raw_u,raw_v,(unsigned long)last,(unsigned long)off);
    else snprintf(out,size,"ERR 109 MOTOR_TEST_COMMAND");
}
