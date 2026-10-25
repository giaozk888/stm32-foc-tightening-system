#ifndef FOC_FEEDBACK_GUARD_STM32_H
#define FOC_FEEDBACK_GUARD_STM32_H
#include "foc_hot_path.h"
/* Fixed register shutdown. Caller supplies CMSIS/STM32 definitions. */
FOC_RAM_PATH static inline void FocFeedbackGuard_OutputOff(void)
{
    DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    TIM1->CCER = 0U;
    TIM1->CR1 &= ~TIM_CR1_CEN;
    __DSB();
}
FOC_RAM_PATH static inline void FocFeedbackGuard_Disarm(void)
{
    TIM7->CR1 = 0U; TIM7->DIER = 0U;
    NVIC_DisableIRQ(TIM7_DAC_IRQn);
    TIM7->SR = 0U;
    NVIC_ClearPendingIRQ(TIM7_DAC_IRQn);
    __DSB();
}
/* Continuous 25 us guard, not a one-shot bridge pulse. Bound the UG wait.
 * Do not share TIM7 with the mutually excluded switching fixture. */
static inline uint8_t FocFeedbackGuard_Prepare(uint32_t timer_hz)
{
    FocFeedbackGuard_Disarm();
    if (timer_hz < 1000000U || timer_hz % 1000000U ||
        timer_hz / 1000000U > 65536U) return 0U;
    TIM7->PSC = timer_hz / 1000000U - 1U;
    TIM7->ARR = 24U; TIM7->CNT = 0U;
    TIM7->EGR = TIM_EGR_UG;
    __DSB();
    uint32_t remaining = 1024U;
    while (!(TIM7->SR & TIM_SR_UIF) && remaining) { --remaining; __NOP(); }
    if (!(TIM7->SR & TIM_SR_UIF)) return 0U;
    TIM7->SR = 0U;
    __DSB();
    NVIC_ClearPendingIRQ(TIM7_DAC_IRQn);
    return !(TIM7->SR & TIM_SR_UIF);
}
static inline void FocFeedbackGuard_Arm(void)
{
    TIM7->DIER = TIM_DIER_UIE;
    NVIC_EnableIRQ(TIM7_DAC_IRQn);
    TIM7->CR1 = TIM_CR1_URS | TIM_CR1_CEN;
    __DSB();
}
#endif
