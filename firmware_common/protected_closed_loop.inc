/* Separate opt-in, single local 20 rpm / 400 ms motor trial. No boot actuation,
 * no arbitrary setpoints, no fault-clear or auto-retry. TIM7 is independent of
 * both ADC and the 1 kHz outer task. Hardware OCP is not fabricated/disabled.
 * Included after original control declarations; original PIs are reused. */
#include "foc_feedback_safety_candidate.h"
#include "foc_feedback_guard_stm32.h"
#include "foc_zero_median.h"
#include "foc_hot_path.h"
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
static FocFeedbackSafety cl_safety;
static FocFeedbackFrame cl_frame;
static FocZeroCal cl_zero;
static FocZeroMedian cl_zero_filter;
static uint32_t cl_seq, cl_last_us, cl_guard_us, cl_psc, cl_irqs;
static uint32_t cl_work_n, cl_work_max, cl_late, cl_outer_n, cl_off_us;
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
static void FOC_ResetController(void);
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s);
#if defined(FOC_STARTUP_TRACE)
#include "foc_startup_trace_binding.inc"
#endif

FOC_COMPACT_HELPER uint8_t ProtectedLoop_GatesMatch(void)
{
    uint32_t sd=(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin)!=0U;
    uint32_t moe=TIM1->BDTR & TIM_BDTR_MOE;
    if (!(TIM1->CR1 & TIM_CR1_CEN) || (TIM1->BDTR & TIM_BDTR_AOE)) return 0U;
    return cl_session.state==CL_RUNNING ?
        (sd && moe && TIM1->CCER==0x555U) : (!sd && !moe && !TIM1->CCER);
}
FOC_COMPACT_HELPER uint8_t ProtectedLoop_TimerHealthy(void)
{
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
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
        NVIC_GetPriority(TIM7_DAC_IRQn)==0U && NVIC_GetPriority(ADC1_2_IRQn)==adc_priority &&
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
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
#if defined(FOC_FAST_MATH)
#define TIM7_DAC_IRQHandler ProtectedLoop_GuardIrqBody
#endif
FOC_HOT_PATH
void TIM7_DAC_IRQHandler(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint32_t sr=TIM7->SR; TIM7->SR=0U;
    if (!cl_armed) { __set_PRIMASK(mask); return; }
    ++cl_irqs; uint32_t now=AS5047P_DmaNowUs();
    uint32_t flags=ProtectedLoop_Health(now);
    if (!(sr & TIM_SR_UIF) || now==cl_guard_us) flags|=CL_BAD_TIMER;
    cl_guard_us=now;
#if defined(FOC_GUARD_FAST_PATH)
    uint8_t expired=(uint8_t)ClSession_Expired(&cl_session,now);
    if (expired) ProtectedLoop_Stop();
#else
    if (ClSession_Expired(&cl_session,now)) ProtectedLoop_Stop();
#endif
    if (flags) ProtectedLoop_EmergencyOff(flags);
    else if ((uint32_t)(now-cl_last_us)>100U) ProtectedLoop_EmergencyOff(CL_BAD_ADC);
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
#if defined(FOC_IRQ_SOURCE_TRACE) || defined(FOC_PWM_BOUNDARY_TRACE)
    FocIrqSource_Enter(FOC_IRQ_GUARD); ProtectedLoop_GuardIrqBody(); FocIrqSource_Leave(FOC_IRQ_GUARD);
#else
    FocIrqLoad_Enter(); ProtectedLoop_GuardIrqBody(); FocIrqLoad_Leave();
#endif
}
#endif
static int ProtectedLoop_Init(void)
{
    if (cl_initialized || foc_fault || adc_fault || !encoder_valid) return 0;
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
    HAL_NVIC_SetPriority(TIM7_DAC_IRQn,0U,0U);
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
    HAL_NVIC_SetPriority(ADC1_2_IRQn,2U,0U);
#else
    HAL_NVIC_SetPriority(ADC1_2_IRQn,1U,0U);
#endif
    cl_last_us=cl_guard_us=AS5047P_DmaNowUs(); cl_seq=injected_seq_count;
    cl_armed=1U; TIM1->CR1|=TIM_CR1_CEN; FocFeedbackGuard_Arm();
    __set_PRIMASK(mask);
    uint32_t deadline=HAL_GetTick()+FOC_ZERO_TIMEOUT_MS;
    while (cl_session.state==CL_CALIBRATING && (int32_t)(HAL_GetTick()-deadline)<0)
        vTaskDelay(pdMS_TO_TICKS(1U));
    if (cl_session.state!=CL_READY) { ProtectedLoop_EmergencyOff(CL_BAD_ZERO); return 0; }
#if defined(FOC_LATEST_ORIGINAL_FSM)
    /* Readiness is not actuation. Explicit ANALOG SAFE/Shutdown cannot re-enter
     * this one-shot initialization. A trial must confirm/reset first. */
    if (cl_boot_confirmed) analog_safe_latched=0U;
#endif
    return 1;
}
static uint8_t ProtectedLoop_Ready(void)
{
#if defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_RC_DEFERRED_SHADOW)
    return 0U; /* Observer builds never admit motor actuation. */
#else
    return cl_session.state==CL_READY && !cl_session.used && cl_armed &&
        !cl_request && !adc_fault && !foc_fault && run_zero_cal_done &&
        !fw_update.active && cl_boot_confirmed && UART_Async_IsReady() &&
#if defined(FOC_ADC_RC_PROTECTED_CANDIDATE)
        FocAdcTiming_RcActuationReady() &&
#endif
        cl_work_n && cl_outer_n && AS5047P_DmaIsPeriodic() &&
        cl_safety.protection.result==FOC_OC_CLEAR &&
        ProtectedLoop_TimerHealthy() && ProtectedLoop_GatesMatch() &&
        (uint32_t)(AS5047P_DmaNowUs()-cl_last_us)<=100U &&
        encoder_valid && isfinite(encoder_speed_rpm) && fabsf(encoder_speed_rpm)<=2.0f &&
        motor_control_mode==MOTOR_MODE_IDLE && !Tightening_IsBusy() && !tightening_start_request;
#endif
}
FOC_RAM_PATH static void ProtectedLoop_SetDuty(float du,float dv,float dw)
{
#if defined(FOC_RC_DEFERRED_SHADOW)
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
#elif defined(FOC_ADAPTIVE_FILTER_EXPERIMENT)
    (void)du; (void)dv; (void)dw;
    /* Shadow FOC must keep its ADC-only TIM1 trigger alive. EmergencyOff /
     * Shutdown still stop CEN; this path never starts/restarts the timer. */
    DRIVER_SD_GPIO_Port->BSRR=(uint32_t)DRIVER_SD_Pin<<16U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    TIM1->CCER=0U;
    __DSB();
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
#if defined(FOC_ADAPTIVE_FILTER_EXPERIMENT) || defined(FOC_RC_DEFERRED_SHADOW)
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
static void ProtectedLoop_Command(const char *cmd,char *out,size_t size)
{
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
    if (!strcmp(cmd,"MOTOR TEST FILTER")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        FocAdaptiveNoise u=cl_safety.filter.noise[0],v=cl_safety.filter.noise[1];
        __set_PRIMASK(mask);
        snprintf(out,size,"OK MOTOR TEST FILTER ADAPT=1 HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT " DELAY_PAIRS=1 JUMP=%u,%u NOISE_Q8=%u,%u LEARNED=%lu,%lu",
            FocAdaptive_Jump(&u),FocAdaptive_Jump(&v),u.noise_q8,v.noise_q8,
            (unsigned long)u.learned,(unsigned long)v.learned); return;
    }
#if defined(FOC_ZERO_ALL_REJECTED_DIAG)
    if (!strcmp(cmd,"MOTOR TEST ZERO POLICY")) {
        snprintf(out,size,"OK ZERO POLICY DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V"); return;
    }
#endif
    if (!strcmp(cmd,"MOTOR TEST ZERO ROBUST")) {
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
        snprintf(out,size,"OK MOTOR TEST ZERO STATE=%u REASON=%u NOM=%u U0=%u V0=%u N=%lu RET=%lu RNG=%u:%u,%u:%u RAW_STATE=%u RAW_REASON=%u",
            z.state,z.reason,z.nominal,z.zero_u,z.zero_v,(unsigned long)z.count,(unsigned long)z.restarts,
            z.min_u,z.max_u,z.min_v,z.max_v,cl_zero_filter.raw.state,cl_zero_filter.raw.reason);
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
#if defined(FOC_IRQ_COMPACT)
    else if (!strcmp(cmd,"MOTOR TEST COMPACT"))
        snprintf(out,size,"OK MOTOR TEST COMPACT ENABLED=1 HARD_OFF=" FOC_PROFILE_HARD_OFF_TEXT " FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50");
#endif
    else if (!strcmp(cmd,"MOTOR TEST TIMING"))
        snprintf(out,size,"OK MOTOR TEST TIMING CLOCK_HZ=1000000 WORK=%lu MAX_US=%lu LATE=%lu IRQ=%lu OUTER=%lu LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000",
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
