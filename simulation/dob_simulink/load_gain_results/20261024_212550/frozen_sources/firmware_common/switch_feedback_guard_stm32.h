#ifndef SWITCH_FEEDBACK_GUARD_STM32_H
#define SWITCH_FEEDBACK_GUARD_STM32_H
/* Caller provides STM32/CMSIS definitions and holds the short IRQ mask.
 * Wait until UG has reached the timer, THEN clear UIF/pending before UIE.
 * Clearing SR immediately after EGR is not proof that the update completed.
 */
static inline uint8_t SwitchGuard_Prepare(void)
{
    NVIC_DisableIRQ(TIM7_DAC_IRQn);
    TIM7->CR1 = 0U; TIM7->DIER = 0U; TIM7->SR = 0U;
    TIM7->PSC = 16999U; TIM7->ARR = 1899U; TIM7->CNT = 0U;
    TIM7->EGR = TIM_EGR_UG;
    __DSB();
    uint32_t remaining = 1024U;
    while (!(TIM7->SR & TIM_SR_UIF) && remaining) { --remaining; __NOP(); }
    if (!(TIM7->SR & TIM_SR_UIF)) return 0U;
    TIM7->SR = 0U;
    __DSB();
    HAL_NVIC_ClearPendingIRQ(TIM7_DAC_IRQn);
    return !(TIM7->SR & TIM_SR_UIF);
}
static inline void SwitchGuard_Arm(void)
{
    TIM7->DIER = TIM_DIER_UIE;
    NVIC_EnableIRQ(TIM7_DAC_IRQn);
    TIM7->CR1 = TIM_CR1_URS | TIM_CR1_OPM | TIM_CR1_CEN;
    __DSB();
}
/* Periodic 25us guard for the explicitly bounded filtered bridge only. */
static inline uint8_t SwitchFilteredGuard_Prepare(void)
{
    NVIC_DisableIRQ(TIM7_DAC_IRQn);
    TIM7->CR1=0U; TIM7->DIER=0U; TIM7->SR=0U;
    TIM7->PSC=169U; TIM7->ARR=24U; TIM7->CNT=0U; TIM7->EGR=TIM_EGR_UG;
    __DSB();
    uint32_t remaining=1024U;
    while (!(TIM7->SR&TIM_SR_UIF) && remaining) { --remaining; __NOP(); }
    if (!(TIM7->SR&TIM_SR_UIF)) return 0U;
    TIM7->SR=0U; __DSB(); HAL_NVIC_ClearPendingIRQ(TIM7_DAC_IRQn);
    return !(TIM7->SR&TIM_SR_UIF);
}
static inline void SwitchFilteredGuard_Arm(void)
{
    TIM7->DIER=TIM_DIER_UIE; NVIC_EnableIRQ(TIM7_DAC_IRQn);
    TIM7->CR1=TIM_CR1_URS|TIM_CR1_CEN; __DSB();
}
#endif
