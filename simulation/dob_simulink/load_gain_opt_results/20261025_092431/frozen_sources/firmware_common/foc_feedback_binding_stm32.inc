/* Included after IsolatedBench_Locked. Dedicated hard-off profile ONLY.
 * TIM2 is READ ONLY here: the encoder owns its 1 MHz timebase/comparators.
 * TIM7 priority 0 polls independently; ADC priority 1 in this profile only.
 * Short PRIMASK sections serialize guardian state. Never hold the mask over
 * FOC arithmetic, formatting, HAL waits, DMA cleanup or RTOS calls.
 */
#include "foc_feedback_guard_stm32.h"
static FocFeedbackSafety foc_feedback_safety;
static FocFeedbackFrame foc_feedback_control_frame;
static volatile uint8_t foc_feedback_armed, foc_feedback_zero_ready;
static uint32_t foc_feedback_last_us, foc_feedback_last_seq;
static uint32_t foc_feedback_timer_psc, foc_feedback_guard_irqs;
static uint32_t foc_feedback_guard_last_us;
static uint32_t foc_feedback_work_n, foc_feedback_work_last_us, foc_feedback_work_max_us;
static uint32_t foc_feedback_work_late, foc_feedback_test_us;
static uint8_t foc_feedback_test_used; /* One stopped-stream injection per boot. */
static uint32_t foc_feedback_observed_seq, foc_feedback_observed_us;
static uint16_t foc_feedback_observed_u, foc_feedback_observed_v;
typedef struct {
    uint32_t seq, sample_us, off_us, last_valid_us;
    uint32_t flags, guard_irqs, sd, bdtr, ccer, cr1;
    uint16_t u, v;
    uint8_t valid, reason;
} FocFeedbackFault;
static FocFeedbackFault foc_feedback_fault;
#define FOC_FAULT_FEEDBACK_PROTECTION 9U

#if defined(FOC_TIMEOUT_DIAGNOSTICS)
static void FaultDiag_FillProtected(volatile FocFaultSnapshot *s)
{
    const FocFilteredProtection *p=&foc_feedback_safety.protection;
    const FocTimeoutLatch *t=&p->timeout;
    if (t->reason) {
        s->timeout=(FocTimeoutEvidence){t->reason,t->now_us,t->reference_us,
            t->now_us-t->reference_us,t->limit_us,p->last_us,p->pending_us,p->pending,p->misses};
        s->timeout_reason=t->reason;
    }
}
#endif

static void FocFeedbackBinding_Disarm(void)
{
    foc_feedback_armed = 0U;
    FocFeedbackGuard_Disarm();
}

void FocFeedbackBinding_EmergencyOff(uint32_t flags)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    /* Close the actual register gates FIRST; evidence recording comes after. */
    FocFeedbackGuard_OutputOff();
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
    if (!foc_fault_snapshot.valid) foc_fault_snapshot.protection_flags=foc_feedback_safety.protection.fault_flags|flags;
    FaultDiag_Capture(FOC_DIAG_PROTECTION,
        foc_feedback_safety.protection.result==FOC_OC_TRIPPED ? foc_feedback_safety.protection.reason :
        (flags & (FOC_FP_HW_TRIP | FOC_FP_DRIVER_FAULT)) ? FOC_FP_HARDWARE : FOC_FP_HEALTH,
        (flags & FOC_FB_COMPUTE_LATE) ? FOC_TO_COMPUTE_DEADLINE :
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
        (flags & FOC_FB_CONTROL_LEASE_EXPIRED) ? FOC_TO_CONTROL_LEASE :
#endif
        (flags & FOC_FB_ENCODER_INVALID) ? encoder_timeout_reason :
        (FocTimeoutReason)foc_feedback_safety.protection.timeout.reason,
        tightening_test_elapsed_ms,0U);
#endif
    FocFeedbackBinding_Disarm();
    foc_feedback_safety.protection.fault_flags |= flags;
    (void)FocFp_Trip(&foc_feedback_safety.protection,
        (flags & (FOC_FP_HW_TRIP | FOC_FP_DRIVER_FAULT)) ? FOC_FP_HARDWARE : FOC_FP_HEALTH, 0U);
    /* Preserve the FIRST post-register-shutdown record. This is not an
     * oscilloscope measurement of a physical gate or driver trip. */
    if (!foc_feedback_fault.valid) {
        foc_feedback_fault = (FocFeedbackFault){
            .seq = foc_feedback_observed_seq, .sample_us = foc_feedback_observed_us,
            .off_us = AS5047P_DmaNowUs(), .last_valid_us = foc_feedback_last_us,
            .flags = foc_feedback_safety.protection.fault_flags,
            .guard_irqs = foc_feedback_guard_irqs,
            .sd = (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) != 0U,
            .bdtr = TIM1->BDTR, .ccer = TIM1->CCER, .cr1 = TIM1->CR1,
            .u = foc_feedback_observed_u, .v = foc_feedback_observed_v,
            .valid = 1U, .reason = (uint8_t)foc_feedback_safety.protection.reason
        };
    }
    foc_feedback_safety.frame.ready = foc_feedback_control_frame.ready = 0U;
    foc_feedback_zero_ready = 0U;
    if (!foc_fault) foc_fault_reason = FOC_FAULT_FEEDBACK_PROTECTION;
    adc_fault = foc_fault = analog_safe_latched = 1U;
    foc_enable = isolated_running = isolated_zero_ready = run_zero_cal_done = 0U;
    foc_id_ref_A = foc_iq_ref_A = 0.0f;
    isolated_end_ms = HAL_GetTick();
    isolated_zero_shutdown_pending = 1U; /* Foreground owns encoder DMA cleanup. */
    __DMB(); __set_PRIMASK(mask);
}

static uint8_t FocFeedbackBinding_TimerHealthy(void)
{
    return (RCC->APB1ENR1 & (RCC_APB1ENR1_TIM2EN | RCC_APB1ENR1_TIM7EN)) ==
            (RCC_APB1ENR1_TIM2EN | RCC_APB1ENR1_TIM7EN) &&
        NVIC_GetPriority(TIM7_DAC_IRQn) == 0U && NVIC_GetPriority(ADC1_2_IRQn) == 1U &&
        (TIM2->CR1 & TIM_CR1_CEN) && TIM2->PSC == foc_feedback_timer_psc &&
        TIM2->ARR == UINT32_MAX && TIM7->PSC == foc_feedback_timer_psc &&
        TIM7->ARR == 24U && TIM7->DIER == TIM_DIER_UIE &&
        (TIM7->CR1 & (TIM_CR1_CEN | TIM_CR1_URS | TIM_CR1_OPM)) ==
            (TIM_CR1_CEN | TIM_CR1_URS) && NVIC_GetEnableIRQ(TIM7_DAC_IRQn);
}

/* Caller holds PRIMASK; no ISR can consume a partially initialized session. */
static int FocFeedbackBinding_Arm(uint16_t nominal)
{
    if (foc_feedback_safety.protection.result == FOC_OC_TRIPPED) return 0;
    __HAL_RCC_TIM7_CLK_ENABLE();
    uint32_t hz = HAL_RCC_GetPCLK1Freq();
    if ((RCC->CFGR & RCC_CFGR_PPRE1) != 0U) hz *= 2U;
    FocFeedbackSafetyConfig cfg = {
        .protection = {FOC_CURRENT_TRIP_A, 100U, 100U,
                       FOC_FB_REPAIR_HITS_PER_32, FOC_FB_REPAIR_STREAK},
        .zero_u = nominal, .zero_v = nominal,
        .count_to_A = (float)ADC_VREF_MV / ((float)ADC_FULL_SCALE * CURRENT_GAIN_MV_PER_A)
    };
    uint32_t now = AS5047P_DmaNowUs();
    if (FocFeedbackSafety_Begin(&foc_feedback_safety, cfg, now) == FOC_OC_TRIPPED ||
        !IsolatedBench_Locked() || !FocFeedbackGuard_Prepare(hz)) {
        FocFeedbackBinding_EmergencyOff(FOC_FB_TIMER_INVALID); return 0;
    }
    foc_feedback_timer_psc = hz / 1000000U - 1U;
    if (!(TIM2->CR1 & TIM_CR1_CEN) || TIM2->PSC != foc_feedback_timer_psc ||
        TIM2->ARR != UINT32_MAX) {
        FocFeedbackBinding_EmergencyOff(FOC_FB_TIMER_INVALID); return 0;
    }
    foc_feedback_last_us = now; foc_feedback_last_seq = injected_seq_count;
    foc_feedback_guard_irqs = 0U;
    foc_feedback_guard_last_us = now;
    foc_feedback_work_n = foc_feedback_work_last_us = foc_feedback_work_max_us = 0U;
    foc_feedback_work_late = 0U;
    foc_feedback_observed_seq = injected_seq_count; foc_feedback_observed_us = now;
    foc_feedback_observed_u = foc_feedback_observed_v = nominal;
    foc_feedback_zero_ready = 0U;
    foc_feedback_control_frame = (FocFeedbackFrame){0};
    HAL_NVIC_SetPriority(TIM7_DAC_IRQn, 0U, 0U);
    HAL_NVIC_SetPriority(ADC1_2_IRQn, 1U, 0U);
    foc_feedback_armed = 1U;
    FocFeedbackGuard_Arm();
    if (!FocFeedbackBinding_TimerHealthy()) {
        FocFeedbackBinding_EmergencyOff(FOC_FB_TIMER_INVALID); return 0;
    }
    return 1;
}

/* Only the qualified calibration-to-computation transition initializes zeros.
 * An existing fault is never cleared by successful calibration or new data. */
static void FocFeedbackBinding_ZeroReady(void)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    if (!foc_feedback_armed || foc_feedback_safety.protection.result == FOC_OC_TRIPPED) {
        __set_PRIMASK(mask); return;
    }
    FocFeedbackSafetyConfig cfg = foc_feedback_safety.cfg;
    cfg.zero_u = iu_zero_raw; cfg.zero_v = iv_zero_raw;
    if (FocFeedbackSafety_Begin(&foc_feedback_safety, cfg, AS5047P_DmaNowUs()) == FOC_OC_TRIPPED)
        FocFeedbackBinding_EmergencyOff(FOC_FP_ZERO_INVALID);
    else foc_feedback_zero_ready = 1U;
    __set_PRIMASK(mask);
}

static uint32_t FocFeedbackBinding_Health(void)
{
    return (adc_fault ? FOC_FP_ADC_INVALID : 0U) |
        (!encoder_valid ? FOC_FB_ENCODER_INVALID : 0U) |
        (!FocFeedbackBinding_TimerHealthy() ? FOC_FB_TIMER_INVALID : 0U) |
        (!IsolatedBench_Locked() ? FOC_FB_OUTPUT_LOCK_LOST : 0U);
}

/* Seen on EVERY ADC pair, including calibration. Invalid/gapped streams never
 * refresh the timeout into appearing healthy. There is no amplitude decision. */
static int FocFeedbackBinding_PhysicalSeen(uint16_t u, uint16_t v)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    if (!foc_feedback_armed) { __set_PRIMASK(mask); return 0; }
    uint32_t now = AS5047P_DmaNowUs(), flags = FocFeedbackBinding_Health();
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
    if (ControlChain_DeadlineReached(now)) flags |= FOC_FB_CONTROL_LEASE_EXPIRED;
#endif
    foc_feedback_observed_seq = injected_seq_count; foc_feedback_observed_us = now;
    foc_feedback_observed_u = u; foc_feedback_observed_v = v;
    FocFilteredProtectionReason reason = FOC_FP_NONE;
    if (flags) reason = FOC_FP_HEALTH;
    else if (u > ADC_FULL_SCALE || v > ADC_FULL_SCALE) reason = FOC_FP_RAW_INVALID;
    else if ((uint32_t)(now - foc_feedback_last_us) > 100U) reason = FOC_FP_TIMEOUT;
    else if ((uint32_t)(injected_seq_count - foc_feedback_last_seq) != 1U ||
             now == foc_feedback_last_us) reason = FOC_FP_SEQUENCE;
    if (reason != FOC_FP_NONE) {
        if (reason==FOC_FP_TIMEOUT)
            (void)FocFp_TripTimeout(&foc_feedback_safety.protection,FOC_TO_ADC_GUARD,
                now,foc_feedback_last_us,100U,0U);
        else (void)FocFp_Trip(&foc_feedback_safety.protection, reason, 0U);
        FocFeedbackBinding_EmergencyOff(flags);
        __set_PRIMASK(mask); return 0;
    }
    foc_feedback_last_us = now; foc_feedback_last_seq = injected_seq_count;
    __set_PRIMASK(mask); return 1;
}

static int FocFeedbackBinding_Control(uint16_t u, uint16_t v)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    if (!foc_feedback_armed || !foc_feedback_zero_ready) { __set_PRIMASK(mask); return 0; }
    uint32_t flags = FocFeedbackBinding_Health();
    FocOcConfirmResult result = FocFeedbackSafety_Push(&foc_feedback_safety,
        injected_seq_count, foc_feedback_last_us, u, v, encoder_theta_e_pred,
        flags, (uint8_t)IsolatedBench_Locked());
    int ready = 0;
    if (result != FOC_OC_TRIPPED)
        ready = FocFeedbackSafety_Take(&foc_feedback_safety, AS5047P_DmaNowUs(),
            flags, (uint8_t)IsolatedBench_Locked(), &foc_feedback_control_frame);
    if (foc_feedback_safety.protection.result == FOC_OC_TRIPPED)
        FocFeedbackBinding_EmergencyOff(flags);
    __set_PRIMASK(mask); return ready;
}

/* Wall-clock interval from PhysicalSeen's timestamp through selector + FOC.
 * Includes preemption; excludes ADC interrupt-entry/read latency. No WCET claim.
 * 1 us clock resolution: >=50 us cannot demonstrate a completed 20 kHz slot. */
static void FocFeedbackBinding_WorkEnd(uint32_t start_us)
{
    uint32_t elapsed = AS5047P_DmaNowUs() - start_us;
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    FocFp_Increment(&foc_feedback_work_n);
    foc_feedback_work_last_us = elapsed;
    if (elapsed > foc_feedback_work_max_us) foc_feedback_work_max_us = elapsed;
    if (elapsed >= 50U) {
        FocFp_Increment(&foc_feedback_work_late);
        if (foc_feedback_armed) FocFeedbackBinding_EmergencyOff(FOC_FB_COMPUTE_LATE);
    }
    __set_PRIMASK(mask);
}

/* Hard-OFF diagnostic injection only. Stops the ADC trigger, leaves TIM7
 * running to prove independent timeout. Never enables SD/MOE/CCER or restarts.
 * Protocol caller also enforces local-console-only and no boot trial. */
static int FocFeedbackBinding_TestTimeout(void)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    if (foc_feedback_test_used || !foc_feedback_armed || !foc_feedback_zero_ready ||
        !IsolatedBench_Locked() || !FocFeedbackBinding_TimerHealthy() ||
        foc_feedback_safety.protection.result != FOC_OC_CLEAR) {
        __set_PRIMASK(mask); return 0;
    }
    foc_feedback_test_us = AS5047P_DmaNowUs();
    foc_feedback_test_used = 1U;
    TIM1->CR1 &= ~TIM_CR1_CEN;
    __DSB();
    __set_PRIMASK(mask); return 1;
}

void TIM7_DAC_IRQHandler(void)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    uint32_t sr = TIM7->SR; TIM7->SR = 0U;
    if (!foc_feedback_armed) { __set_PRIMASK(mask); return; }
    FocFp_Increment(&foc_feedback_guard_irqs);
    uint32_t now = AS5047P_DmaNowUs(), flags = FocFeedbackBinding_Health();
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
    if (ControlChain_DeadlineReached(now)) flags |= FOC_FB_CONTROL_LEASE_EXPIRED;
#endif
    if (!(sr & TIM_SR_UIF)) flags |= FOC_FB_TIMER_INVALID;
    /* A configured/running TIM2 is not enough: it must actually advance
     * between independently scheduled guard interrupts. */
    if (now == foc_feedback_guard_last_us) flags |= FOC_FB_TIMER_INVALID;
    foc_feedback_guard_last_us = now;
    if (flags) FocFeedbackBinding_EmergencyOff(flags);
    else if ((uint32_t)(now - foc_feedback_last_us) > 100U) {
        (void)FocFp_TripTimeout(&foc_feedback_safety.protection,FOC_TO_ADC_GUARD,
            now,foc_feedback_last_us,100U,0U);
        FocFeedbackBinding_EmergencyOff(0U);
    } else if (foc_feedback_zero_ready &&
        FocFeedbackSafety_Poll(&foc_feedback_safety, now, 0U, 1U) == FOC_OC_TRIPPED)
        FocFeedbackBinding_EmergencyOff(0U);
    __set_PRIMASK(mask);
}

static void FocFeedbackBinding_Format(char *out, size_t size)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    FocFilteredProtection p = foc_feedback_safety.protection;
    uint32_t irqs = foc_feedback_guard_irqs;
    uint8_t armed = foc_feedback_armed, zero = foc_feedback_zero_ready;
    __set_PRIMASK(mask);
    snprintf(out, size,
        "OK BENCH PROTECTION HARD_OFF=1 MOTOR_QUALIFIED=0 RAW=VALIDITY_ONLY FILTERED=2_OF_3 "
        "STATE=%u REASON=%u FLAGS=%lu MASK=%u ARMED=%u ZERO=%u GUARD_US=25 IRQ=%lu "
        "RAW_N=%lu FEEDBACK_N=%lu REPAIRED=%lu REPAIR_MAX=%u STREAK_MAX=%u",
        (unsigned)p.result, (unsigned)p.reason, (unsigned long)p.fault_flags, p.trip_mask,
        armed, zero, (unsigned long)irqs, (unsigned long)p.raw_pairs,
        (unsigned long)p.feedback_pairs, (unsigned long)p.repaired_pairs,
        p.cfg.repair_hits_per_32, p.cfg.repair_streak);
}

static void FocFeedbackBinding_TimingFormat(char *out, size_t size)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    uint32_t n = foc_feedback_work_n, last = foc_feedback_work_last_us;
    uint32_t max = foc_feedback_work_max_us, late = foc_feedback_work_late;
    uint32_t test_us = foc_feedback_test_us;
    uint8_t used = foc_feedback_test_used;
    __set_PRIMASK(mask);
    snprintf(out, size, "OK BENCH PROTECTION TIMING MOTOR_QUALIFIED=0 CLOCK_HZ=1000000 "
        "SCOPE=PAIR_CHECK_TO_FOC_END N=%lu LAST_US=%lu MAX_US=%lu LATE=%lu "
        "BUDGET_US=50 TEST_USED=%u TEST_US=%lu",
        (unsigned long)n, (unsigned long)last, (unsigned long)max,
        (unsigned long)late, used, (unsigned long)test_us);
}

static void FocFeedbackBinding_FaultFormat(char *out, size_t size)
{
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    FocFeedbackFault f = foc_feedback_fault;
    __set_PRIMASK(mask);
    snprintf(out, size, "OK BENCH PROTECTION FAULT MOTOR_QUALIFIED=0 VALID=%u "
        "REASON=%u FLAGS=%lu SEQ=%lu RAW=%u,%u SAMPLE_US=%lu LAST_VALID_US=%lu "
        "OFF_US=%lu GUARD_IRQ=%lu SD=%lu BDTR=%08lX CCER=%08lX CR1=%08lX",
        f.valid, f.reason, (unsigned long)f.flags, (unsigned long)f.seq,
        f.u, f.v, (unsigned long)f.sample_us, (unsigned long)f.last_valid_us,
        (unsigned long)f.off_us, (unsigned long)f.guard_irqs,
        (unsigned long)f.sd, (unsigned long)f.bdtr,
        (unsigned long)f.ccer, (unsigned long)f.cr1);
}
