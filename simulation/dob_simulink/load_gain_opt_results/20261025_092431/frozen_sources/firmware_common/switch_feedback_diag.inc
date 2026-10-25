/* Opt-in standalone OPEN-LOAD diagnostic. Never a motor-control service.
 * Only StartupTask owns ADC reconfiguration. A local console request queues
 * a start; ISR and independent high-priority TIM7 both shut down outputs.
 */
#include "switch_feedback_core.h"
#include "switch_feedback_guard_stm32.h"
#if defined(SWITCH_SIGNAL_ONLY_DIAGNOSTIC)
#define SWITCH_BRIDGE_COMPILED "0"
#else
#define SWITCH_BRIDGE_COMPILED "1"
#endif
static volatile uint8_t switch_active, switch_reason, switch_attempts;
static uint8_t switch_completed, switch_wave_verified;
static uint32_t switch_started_ms, switch_elapsed_cycles, switch_start_cycles;
static volatile uint32_t switch_irq_sr, switch_irq_count, switch_irq_cnt;
static SwitchFeedbackStats switch_stats;
static uint16_t switch_raw[SWITCH_FEEDBACK_PAIRS][2];
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
#include "bridge_feedback_filter_core.h"
static BridgeFeedbackFilter switch_filter;
static uint32_t switch_filter_us[BRIDGE_FILTER_PAIRS];
static volatile uint32_t switch_filter_work_cycles;
static uint8_t SwitchFeedback_ActiveConfig(void);
#endif
static QueueHandle_t switch_requests, switch_replies;
static StaticQueue_t switch_request_ctrl, switch_reply_ctrl;
static uint8_t switch_request_storage, switch_reply_storage;
static HAL_StatusTypeDef ZeroAdcOwner_LiveSample(void);

/* No RTOS/HAL calls: also called from priority-1 TIM7 and core exceptions. */
void SwitchFeedback_EmergencyOff(uint32_t reason)
{
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    TIM1->CCER = 0U;
    TIM1->CR1 &= ~TIM_CR1_CEN;
    TIM7->CR1 = 0U;
    TIM7->DIER = 0U;
    NVIC_DisableIRQ(TIM7_DAC_IRQn);
    if (switch_active) {
        switch_elapsed_cycles = DWT->CYCCNT - switch_start_cycles;
        switch_reason = (uint8_t)reason;
        switch_active = 0U;
    }
}
void TIM7_DAC_IRQHandler(void)
{
    switch_irq_sr = TIM7->SR;
    switch_irq_cnt = TIM7->CNT;
    ++switch_irq_count;
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
    if (switch_active && (switch_stats.mode==SWITCH_FILTERED_BRIDGE ||
                          switch_stats.mode==SWITCH_FILTERED_GUARD)) {
        TIM7->SR=0U;
        uint32_t now=(DWT->CYCCNT-switch_start_cycles)/170U;
        if (!(switch_irq_sr&TIM_SR_UIF) || !SwitchFeedback_ActiveConfig())
            SwitchFeedback_EmergencyOff(SWITCH_CONFIG);
        else if (now>=BRIDGE_FILTER_MAX_US || switch_irq_count>=2000U)
            SwitchFeedback_EmergencyOff(SWITCH_TIME);
        else if (switch_stats.mode==SWITCH_FILTERED_BRIDGE &&
                 FocFp_Poll(&switch_filter.protection,now,0U)==FOC_OC_TRIPPED)
            SwitchFeedback_EmergencyOff(SWITCH_FILTERED_TRIP);
        return;
    }
#endif
    SwitchFeedback_EmergencyOff((switch_irq_sr & TIM_SR_UIF) ? SWITCH_TIME : SWITCH_CONFIG);
    TIM7->SR = 0U;
}
void vApplicationMallocFailedHook(void)
{
    SwitchFeedback_EmergencyOff(SWITCH_CORE_FAULT);
    __disable_irq(); for (;;) { }
}
void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task; (void)name;
    SwitchFeedback_EmergencyOff(SWITCH_CORE_FAULT);
    __disable_irq(); for (;;) { }
}
static uint8_t SwitchFeedback_TimerConfig(void)
{
    /* Reject clock/polarity/mode changes, including AOE, asymmetric deadtime
     * or alternate GPIO functions. 0xAA => (64+42)*2 ticks, ~1.247 us. */
    if (HAL_RCC_GetHCLKFreq() != 170000000U || HAL_RCC_GetPCLK1Freq() != 170000000U ||
        HAL_RCC_GetPCLK2Freq() != 170000000U || !FocAdcClock_IsExpected() ||
        TIM1->PSC || TIM1->ARR != 4249U || TIM1->CCR1 != 2125U ||
        TIM1->CCR2 != 2125U || TIM1->CCR3 != 2125U || TIM1->CCR4 != 3500U ||
        (TIM1->CR1 & (TIM_CR1_CMS | TIM_CR1_CKD)) != TIM_COUNTERMODE_CENTERALIGNED1 ||
        (TIM1->BDTR & (TIM_BDTR_DTG | TIM_BDTR_AOE)) != 0xAAU ||
        (TIM1->CCMR1 & (TIM_CCMR1_CC1S | TIM_CCMR1_CC2S |
                       TIM_CCMR1_OC1M | TIM_CCMR1_OC2M)) != 0x6060U ||
        (TIM1->CCMR2 & (TIM_CCMR2_CC3S | TIM_CCMR2_CC4S |
                       TIM_CCMR2_OC3M | TIM_CCMR2_OC4M)) != 0x7060U ||
        TIM1->DTR2 || TIM1->DIER ||
        (TIM1->CR2 & TIM_CR2_MMS2) != TIM_TRGO2_OC4REF ||
        (TIM1->CR2 & (TIM_CR2_OIS1 | TIM_CR2_OIS1N | TIM_CR2_OIS2 |
                       TIM_CR2_OIS2N | TIM_CR2_OIS3 | TIM_CR2_OIS3N))) return 0U;
    const uint32_t cmask = (3U << 0) | (3U << 2) | (3U << 4);
    const uint32_t bmask = (3U << 0) | (3U << 2) | (3U << 26);
    if ((GPIOC->MODER & cmask) != ((2U << 0) | (2U << 2) | (2U << 4)) ||
        (GPIOB->MODER & bmask) != ((2U << 0) | (2U << 2) | (2U << 26)) ||
        (GPIOC->AFR[0] & 0xFFFU) != 0x222U ||
        (GPIOB->AFR[0] & 0xFFU) != 0x66U ||
        (GPIOB->AFR[1] & (15U << 20)) != (6U << 20) ||
        (GPIOC->MODER & (3U << 12)) != (1U << 12) ||
        (GPIOA->MODER & 15U) != 15U) return 0U;
    return 1U;
}
static void SwitchFeedback_Init(void)
{
    __HAL_RCC_TIM7_CLK_ENABLE();
    SwitchFeedback_EmergencyOff(SWITCH_ABORT);
    /* Independent 190 ms guard, not an RTOS delay and not reset by polling.
     * Normal capture ends at 180 ms. Neither is a certified external cutoff. */
    if (!SwitchGuard_Prepare()) Error_Handler();
    HAL_NVIC_SetPriority(TIM7_DAC_IRQn, 1U, 0U);
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
    /* Timer priority 0 can preempt the HAL ADC prologue/epilogue. The short
     * state push is serialized and measured; no RTOS API runs at this level. */
    HAL_NVIC_SetPriority(ADC1_2_IRQn,1U,0U);
#endif
    TIM1->BDTR = (TIM1->BDTR & ~(TIM_BDTR_DTG | TIM_BDTR_AOE)) | 0xAAU;
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    switch_requests = xQueueCreateStatic(1U, 1U, &switch_request_storage, &switch_request_ctrl);
    switch_replies = xQueueCreateStatic(1U, 1U, &switch_reply_storage, &switch_reply_ctrl);
    if (!switch_requests || !switch_replies) Error_Handler();
}
static uint8_t SwitchFeedback_ActiveConfig(void)
{
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
    if (switch_stats.mode==SWITCH_FILTERED_BRIDGE || switch_stats.mode==SWITCH_FILTERED_GUARD) {
        uint8_t guard=TIM7->PSC==169U && TIM7->ARR==24U &&
            TIM7->CR1==(TIM_CR1_CEN|TIM_CR1_URS) && TIM7->DIER==TIM_DIER_UIE &&
            NVIC_GetEnableIRQ(TIM7_DAC_IRQn) && NVIC_GetPriority(TIM7_DAC_IRQn)==0U &&
            NVIC_GetPriority(ADC1_2_IRQn)==1U && SwitchFeedback_TimerConfig();
        if (switch_stats.mode==SWITCH_FILTERED_GUARD)
            return guard && ZeroRetest_Locked() && !(TIM1->CR1&TIM_CR1_CEN);
        return guard && !adc_fault && !foc_enable && analog_safe_latched &&
            (TIM1->CR1&TIM_CR1_CEN) && TIM1->CCER==0x555U &&
            (TIM1->BDTR&TIM_BDTR_MOE) && (DRIVER_SD_GPIO_Port->ODR&DRIVER_SD_Pin);
    }
#endif
    if (TIM7->PSC != 16999U || TIM7->ARR != 1899U ||
        (TIM7->CR1 & (TIM_CR1_CEN | TIM_CR1_OPM | TIM_CR1_URS)) !=
            (TIM_CR1_CEN | TIM_CR1_OPM | TIM_CR1_URS) ||
        !NVIC_GetEnableIRQ(TIM7_DAC_IRQn)) return 0U;
    if (switch_stats.mode == SWITCH_GUARD)
        return SwitchFeedback_TimerConfig() && ZeroRetest_Locked() &&
            !(TIM1->CR1 & TIM_CR1_CEN) && (TIM7->CR1 & TIM_CR1_CEN) &&
            TIM7->DIER == TIM_DIER_UIE;
    uint8_t pwm = switch_stats.mode != SWITCH_OFF;
    return SwitchFeedback_TimerConfig() && !adc_fault && !foc_enable && analog_safe_latched &&
        (TIM1->CR1 & TIM_CR1_CEN) &&
        TIM1->CCER == (pwm ? 0x555U : 0U) &&
        !!(TIM1->BDTR & TIM_BDTR_MOE) == pwm &&
        !!(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) == (switch_stats.mode == SWITCH_BRIDGE) &&
        (TIM7->CR1 & TIM_CR1_CEN) && TIM7->DIER == TIM_DIER_UIE;
}
static void SwitchFeedback_InjectedPair(uint16_t u, uint16_t v, uint8_t pair)
{
    if (!switch_active) return;
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
    if (switch_stats.mode==SWITCH_FILTERED_BRIDGE) {
        uint32_t began=DWT->CYCCNT;
        /* One bounded serialized owner. TIM7 cannot observe a half-pushed
         * history/state. All ISR work, including stats, is measured below. */
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        if (!pair || adc_fault) SwitchFeedback_EmergencyOff(SWITCH_PAIR);
        else if (!SwitchFeedback_ActiveConfig()) SwitchFeedback_EmergencyOff(SWITCH_CONFIG);
        else {
            uint32_t n=switch_stats.count, now=(began-switch_start_cycles)/170U;
            if (n>=BRIDGE_FILTER_PAIRS) SwitchFeedback_EmergencyOff(SWITCH_CONFIG);
            else {
                switch_raw[n][0]=u; switch_raw[n][1]=v; switch_filter_us[n]=now;
                uint8_t reason=SwitchFeedback_Push(&switch_stats,u,v);
                ++injected_seq_count;
                if (BridgeFilter_Push(&switch_filter,u,v,now)==FOC_OC_TRIPPED)
                    SwitchFeedback_EmergencyOff(SWITCH_FILTERED_TRIP);
                else if (reason) SwitchFeedback_EmergencyOff(reason);
                else if (switch_stats.count==BRIDGE_FILTER_PAIRS) {
                    /* Do not report PASS with an unfinished confirmation. */
                    if (switch_filter.protection.pending) {
                        FocFp_Trip(&switch_filter.protection,FOC_FP_CONFIRMED_CURRENT,
                                   switch_filter.protection.pending_mask);
                        SwitchFeedback_EmergencyOff(SWITCH_FILTERED_TRIP);
                    } else SwitchFeedback_EmergencyOff(SWITCH_DONE);
                }
            }
        }
        uint32_t work=DWT->CYCCNT-began;
        if (work>switch_filter_work_cycles) switch_filter_work_cycles=work;
        if (work>=25U*170U && switch_active) SwitchFeedback_EmergencyOff(SWITCH_WORK_LATE);
        __set_PRIMASK(mask);
        return;
    }
#endif
    if (switch_stats.mode == SWITCH_GUARD || switch_stats.mode==SWITCH_FILTERED_GUARD) {
        SwitchFeedback_EmergencyOff(SWITCH_CONFIG); return;
    }
    if (!pair || adc_fault) { SwitchFeedback_EmergencyOff(SWITCH_PAIR); return; }
    if (!SwitchFeedback_ActiveConfig()) { SwitchFeedback_EmergencyOff(SWITCH_CONFIG); return; }
    uint32_t n = switch_stats.count;
    if (n >= SWITCH_FEEDBACK_PAIRS) { SwitchFeedback_EmergencyOff(SWITCH_CONFIG); return; }
    switch_raw[n][0] = u; switch_raw[n][1] = v;
    uint8_t reason = SwitchFeedback_Push(&switch_stats, u, v);
    ++injected_seq_count;
    if (reason) SwitchFeedback_EmergencyOff(reason);
}
static void SwitchFeedback_Service(void)
{
    if (switch_active) {
        if (!SwitchFeedback_ActiveConfig()) SwitchFeedback_EmergencyOff(SWITCH_CONFIG);
        else if (switch_stats.mode != SWITCH_GUARD &&
                 (uint32_t)(HAL_GetTick() - switch_started_ms) >= 195U)
            SwitchFeedback_EmergencyOff(SWITCH_TIME);
        return;
    }
    if (switch_reason && switch_stats.mode) {
        if (switch_reason == SWITCH_DONE || (switch_stats.mode == SWITCH_GUARD &&
            switch_reason == SWITCH_TIME && !switch_stats.count &&
            switch_irq_count == 1U && (switch_irq_sr & TIM_SR_UIF) &&
            switch_elapsed_cycles >= 185000U * 170U && switch_elapsed_cycles <= 195000U * 170U))
            switch_completed |= 1U << switch_stats.mode;
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        else if (switch_stats.mode==SWITCH_FILTERED_GUARD && switch_reason==SWITCH_TIME &&
                 !switch_stats.count && switch_irq_count==2000U && (switch_irq_sr&TIM_SR_UIF) &&
                 switch_elapsed_cycles>=49500U*170U && switch_elapsed_cycles<=50100U*170U)
            switch_completed |= 1U << SWITCH_FILTERED_GUARD;
#endif
        else switch_wave_verified = 0U; /* Faults revoke later bridge admission. */
    }
    uint8_t mode;
    if (xQueueReceive(switch_requests, &mode, 0U) != pdPASS) return;
    uint8_t admitted = mode >= SWITCH_OFF && mode <= SWITCH_FILTERED_GUARD &&
        !(switch_attempts & (1U << mode)) && !BootHealth_IsCurrentTrial() && !fw_update.active &&
        !zero_retest_running && ZeroRetest_Locked() && zero_retest_adc_ready && !adc_fault &&
        !(TIM1->CR1 & TIM_CR1_CEN) && SwitchFeedback_TimerConfig();
    if (mode == SWITCH_OFF && !admitted) switch_wave_verified = 0U;
    if (mode == SWITCH_PWM) admitted &= (switch_completed & (1U << SWITCH_OFF)) &&
        (switch_completed & (1U << SWITCH_GUARD));
    if (mode == SWITCH_BRIDGE) {
#if defined(SWITCH_SIGNAL_ONLY_DIAGNOSTIC) || defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        admitted = 0U; /* No request/flag can turn on the bridge in this image. */
#else
        /* Existing RAW qualifier must pass, not just the median qualifier.
         * WAVE_VERIFIED is separate physical evidence, never inferred from registers. */
        admitted &= switch_wave_verified &&
            (switch_completed & (1U << SWITCH_GUARD)) &&
            (switch_completed & (1U << SWITCH_PWM)) && zero_retest_cal.state == FOC_ZERO_READY &&
            zero_median.raw.state == FOC_ZERO_READY && !zero_median.outside_nominal &&
            !switch_stats.first_bad_pair && switch_stats.max_reject_streak < 20U;
#endif
    }
    if (mode==SWITCH_FILTERED_BRIDGE) {
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        /* USER_ATTESTED signal evidence, not automated waveform qualification.
         * Fresh zero, OFF baseline and independent guard are still required.
         * Raw amplitude remains recorded; not a hidden old bridge bypass. */
        admitted &= switch_wave_verified && (switch_completed&(1U<<SWITCH_GUARD)) &&
            (switch_completed&(1U<<SWITCH_FILTERED_GUARD)) &&
            (switch_completed&(1U<<SWITCH_OFF)) && zero_retest_cal.state==FOC_ZERO_READY;
#else
        admitted=0U;
#endif
    }
    if (mode==SWITCH_FILTERED_GUARD) {
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        admitted &= (switch_completed&(1U<<SWITCH_GUARD))!=0U;
#else
        admitted=0U;
#endif
    }
    if (admitted && mode != SWITCH_GUARD && mode!=SWITCH_FILTERED_GUARD) admitted &= ZeroAdcOwner_LiveSample() == HAL_OK && analog_live_valid &&
        analog_vdda_boot_valid && analog_vdda_boot_mv >= 3000U && analog_vdda_boot_mv <= 3600U;
    uint32_t bus = (uint32_t)((uint64_t)analog_live_pc4_raw * analog_vdda_boot_mv *
                             ANALOG_VBUS_DIVIDER / ADC_FULL_SCALE);
    if (admitted && mode != SWITCH_GUARD && mode!=SWITCH_FILTERED_GUARD) admitted &= bus >= 10000U && bus <= 14000U;
    if (admitted) {
        uint16_t nominal = analog_vdda_boot_mv ?
            (uint16_t)(FOC_ZERO_NOMINAL_MV * ADC_FULL_SCALE / analog_vdda_boot_mv) : 0U;
        uint16_t u0 = zero_retest_cal.state == FOC_ZERO_READY ? zero_retest_cal.zero_u : nominal;
        uint16_t v0 = zero_retest_cal.state == FOC_ZERO_READY ? zero_retest_cal.zero_v : nominal;
        uint16_t limit = analog_vdda_boot_mv ?
            (uint16_t)(480U * ADC_FULL_SCALE / analog_vdda_boot_mv) : 0U; /* 4 A, .12 V/A */
        uint32_t mask = __get_PRIMASK(); __disable_irq();
        ZeroRetest_Stop();
        uint8_t prepared;
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        if (mode==SWITCH_FILTERED_BRIDGE || mode==SWITCH_FILTERED_GUARD) {
            prepared=SwitchFilteredGuard_Prepare();
            if (mode==SWITCH_FILTERED_BRIDGE)
                prepared &= BridgeFilter_Begin(&switch_filter,u0,v0,analog_vdda_boot_mv);
            switch_filter_work_cycles=0U;
            HAL_NVIC_SetPriority(TIM7_DAC_IRQn,0U,0U);
        } else
#endif
        { prepared=SwitchGuard_Prepare(); HAL_NVIC_SetPriority(TIM7_DAC_IRQn,1U,0U); }
        if (!prepared) {
            SwitchFeedback_EmergencyOff(SWITCH_CONFIG);
            __set_PRIMASK(mask);
            admitted = 0U;
            if (xQueueSend(switch_replies, &admitted, 0U) != pdPASS) Error_Handler();
            return;
        }
        SwitchFeedback_Begin(&switch_stats, mode, u0, v0, limit);
        switch_attempts |= 1U << mode; switch_reason = 0U;
        switch_irq_sr = switch_irq_count = switch_irq_cnt = 0U;
        switch_started_ms = HAL_GetTick(); switch_start_cycles = DWT->CYCCNT;
        __HAL_ADC_CLEAR_FLAG(&hadc1, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
        __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
        TIM1->CNT = 0U; TIM1->EGR = TIM_EGR_UG; TIM1->SR = 0U;
        switch_active = 1U;
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        if (mode==SWITCH_FILTERED_BRIDGE || mode==SWITCH_FILTERED_GUARD) SwitchFilteredGuard_Arm();
        else
#endif
        SwitchGuard_Arm();
        if (mode == SWITCH_PWM || mode == SWITCH_BRIDGE || mode==SWITCH_FILTERED_BRIDGE) {
            TIM1->CCER = 0x555U; TIM1->BDTR |= TIM_BDTR_MOE;
        }
        if (mode != SWITCH_GUARD && mode!=SWITCH_FILTERED_GUARD) TIM1->CR1 |= TIM_CR1_CEN;
        /* All phases use identical 50% PWM; no torque/vector command. */
#if !defined(SWITCH_SIGNAL_ONLY_DIAGNOSTIC)
        if (mode == SWITCH_BRIDGE) DRIVER_SD_GPIO_Port->BSRR = DRIVER_SD_Pin;
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        if (mode==SWITCH_FILTERED_BRIDGE) DRIVER_SD_GPIO_Port->BSRR=DRIVER_SD_Pin;
#endif
#endif
        __set_PRIMASK(mask);
    }
    if (xQueueSend(switch_replies, &admitted, 0U) != pdPASS) {
        SwitchFeedback_EmergencyOff(SWITCH_ABORT); Error_Handler();
    }
}
static void SwitchFeedback_Format(uint32_t id)
{
    SwitchFeedbackStats s;
    uint32_t mask = __get_PRIMASK(); __disable_irq();
    s = switch_stats; uint8_t active = switch_active, reason = switch_reason;
    uint32_t elapsed = active ? DWT->CYCCNT - switch_start_cycles : switch_elapsed_cycles;
    __set_PRIMASK(mask);
    char message[640];
    Protocol_SendFormatted(message, sizeof(message),
        "%lu OK SWITCH PROFILE=OPEN_LOAD_ONLY " FOC_CURRENT_FILTER_FIELDS "MOTOR_READY=0 BRIDGE_COMPILED=" SWITCH_BRIDGE_COMPILED " ACTIVE=%u MODE=%u REASON=%u "
        "N=%lu FN=%lu SUM=%lu,%lu FSUM=%lu,%lu RAW=%u:%u,%u:%u FILTER=%u:%u,%u:%u "
        "OUT=%lu STEPS=%lu STREAK=%lu BAD=%lu:%u,%u LIMIT=%u ZERO=%u,%u "
        "US=%lu IRQ=%lu IRQ_SR=%lu IRQ_CNT=%lu DONE=%u ATTEMPTS=%u WAVE=%u SD=%u MOE=%u CCER=%lu CEN=%u\r\n",
        (unsigned long)id, active, s.mode, reason, (unsigned long)s.count, (unsigned long)s.filtered_count,
        (unsigned long)s.sum_u, (unsigned long)s.sum_v, (unsigned long)s.filtered_sum_u,
        (unsigned long)s.filtered_sum_v, s.min_u,s.max_u,s.min_v,s.max_v,
        s.fmin_u,s.fmax_u,s.fmin_v,s.fmax_v, (unsigned long)s.outside, (unsigned long)s.steps,
        (unsigned long)s.max_reject_streak,(unsigned long)s.first_bad_pair,s.first_bad_u,s.first_bad_v,
        s.raw_limit,s.zero_u,s.zero_v,(unsigned long)(elapsed/170U),
        (unsigned long)switch_irq_count,(unsigned long)switch_irq_sr,(unsigned long)switch_irq_cnt,
        switch_completed,switch_attempts,
        switch_wave_verified,!!(DRIVER_SD_GPIO_Port->ODR&DRIVER_SD_Pin),!!(TIM1->BDTR&TIM_BDTR_MOE),
        (unsigned long)TIM1->CCER,!!(TIM1->CR1&TIM_CR1_CEN));
}
static uint8_t SwitchFeedback_Command(uint32_t id, const char *cmd)
{
    if (strcmp(cmd,"SWITCH STATUS")==0) { SwitchFeedback_Format(id); return 1U; }
    if (strcmp(cmd,"SWITCH ABORT")==0) {
        SwitchFeedback_EmergencyOff(SWITCH_ABORT); SwitchFeedback_Format(id); return 1U;
    }
    if (switch_active) {
        Protocol_SendError(id,PROTO_ERR_BUSY,"SWITCH_ACTIVE_LOCAL_STATUS_OR_ABORT_ONLY"); return 1U;
    }
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
    if (strcmp(cmd,"SWITCH FEEDBACK STATUS")==0) {
        const FocFilteredProtection *s=&switch_filter.protection;
        char message[384];
        Protocol_SendFormatted(message,sizeof(message),
            "%lu OK BRIDGE_FEEDBACK PROFILE=DISCONNECTED_50MS MOTOR_READY=0 "
            "RAW=VALIDITY_ONLY FILTERED=4A_2OF3 REPAIR_BUDGET=6/4 "
            "MAX_US=50000 DEADLINE_US=100 GUARD_US=25 WAVE_SOURCE=USER_ATTESTED "
            "HARDWARE_TRIP_VERIFIED=0 N=%lu FN=%lu REPAIRED=%lu RESULT=%u REASON=%u "
            "LAST_US=%lu WORK_MAX_US=%lu\r\n",
            (unsigned long)id,(unsigned long)s->raw_pairs,(unsigned long)s->feedback_pairs,
            (unsigned long)s->repaired_pairs,s->result,s->reason,(unsigned long)s->last_us,
            (unsigned long)((switch_filter_work_cycles+169U)/170U));
        return 1U;
    }
    if (strncmp(cmd,"SWITCH FILTERED READ ",21U)==0) {
        unsigned index; int end=0;
        if (switch_stats.mode!=SWITCH_FILTERED_BRIDGE ||
            sscanf(cmd+21U,"%u%n",&index,&end)!=1 || cmd[21U+end] ||
            index>=switch_stats.count || index>=BRIDGE_FILTER_PAIRS)
            Protocol_SendError(id,PROTO_ERR_BAD_ARGUMENT,"FILTERED_READ_INDEX");
        else { char message[120]; Protocol_SendFormatted(message,sizeof(message),
            "%lu OK BRIDGE_RAW I=%u U=%u V=%u US=%lu\r\n",(unsigned long)id,index,
            switch_raw[index][0],switch_raw[index][1],(unsigned long)switch_filter_us[index]); }
        return 1U;
    }
#endif
    if (strcmp(cmd,"SWITCH TREND STATUS")==0) {
        /* Allowed only after capture; bounded formatter, no active ISR copy. */
        const SwitchFeedbackStats *s = &switch_stats;
        char message[256];
        Protocol_SendFormatted(message,sizeof(message),
            "%lu OK SWITCH_TREND POLICY=OBSERVER_ONLY MOTOR_READY=0 DELAY_PAIRS=1 "
            "N=%lu SUM=%lu,%lu RANGE=%u:%u,%u:%u REPAIR=%lu,%lu\r\n",
            (unsigned long)id,(unsigned long)s->trend_count,
            (unsigned long)s->trend_sum_u,(unsigned long)s->trend_sum_v,
            s->trend_min_u,s->trend_max_u,s->trend_min_v,s->trend_max_v,
            (unsigned long)s->trend_repairs_u,(unsigned long)s->trend_repairs_v);
        return 1U;
    }
    if (strcmp(cmd,"SWITCH WAVE VERIFIED")==0) {
#if defined(SWITCH_SIGNAL_ONLY_DIAGNOSTIC)
        Protocol_SendError(id,PROTO_ERR_NOT_READY,"BRIDGE_COMPILED_OUT");
#else
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
        if (!(switch_completed&(1U<<SWITCH_OFF)) || !ZeroRetest_Locked())
            Protocol_SendError(id,PROTO_ERR_NOT_READY,"OFF_BASELINE_REQUIRED");
        else { switch_wave_verified=1U; SwitchFeedback_Format(id); }
#else
        if (!(switch_completed & (1U << SWITCH_PWM)) || !ZeroRetest_Locked())
            Protocol_SendError(id,PROTO_ERR_NOT_READY,"PWM_CAPTURE_REQUIRED");
        else { switch_wave_verified=1U; SwitchFeedback_Format(id); }
#endif
#endif
        return 1U;
    }
    if (strncmp(cmd,"SWITCH READ ",12U)==0) {
        unsigned index; int end=0;
        if (sscanf(cmd+12U,"%u%n",&index,&end)!=1 || cmd[12U+end] || index>=switch_stats.count)
            Protocol_SendError(id,PROTO_ERR_BAD_ARGUMENT,"SWITCH_READ_INDEX");
        else { char message[100]; Protocol_SendFormatted(message,sizeof(message),
            "%lu OK SWITCH_RAW I=%u U=%u V=%u\r\n",(unsigned long)id,index,
            switch_raw[index][0],switch_raw[index][1]); }
        return 1U;
    }
    uint8_t mode = !strcmp(cmd,"SWITCH START OFF") ? SWITCH_OFF :
                   !strcmp(cmd,"SWITCH START PWM") ? SWITCH_PWM :
                   !strcmp(cmd,"SWITCH START BRIDGE") ? SWITCH_BRIDGE :
                   !strcmp(cmd,"SWITCH START GUARD") ? SWITCH_GUARD : 0U;
#if defined(SWITCH_FILTERED_BRIDGE_DIAGNOSTIC)
    if (!strcmp(cmd,"SWITCH START FILTERED_BRIDGE")) mode=SWITCH_FILTERED_BRIDGE;
    if (!strcmp(cmd,"SWITCH START FILTERED_GUARD")) mode=SWITCH_FILTERED_GUARD;
#endif
    if (mode) {
        uint8_t admitted=0U;
        if (xQueueSend(switch_requests,&mode,0U)!=pdPASS ||
            xQueueReceive(switch_replies,&admitted,portMAX_DELAY)!=pdPASS || !admitted)
            Protocol_SendError(id,PROTO_ERR_NOT_READY,"SWITCH_ONESHOT_SUPPLY_RAW_ZERO_WAVE_GATE");
        else SwitchFeedback_Format(id);
        return 1U;
    }
    if (strncmp(cmd,"SWITCH ",7U)==0) {
        Protocol_SendError(id,PROTO_ERR_BAD_ARGUMENT,"SWITCH_COMMAND"); return 1U;
    }
    return 0U;
}
