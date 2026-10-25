#ifndef FOC_ADC_CLOCK_STM32_H
#define FOC_ADC_CLOCK_STM32_H
#include "main.h"

/* ES0430 2.7.11: ADC1/ADC2 on the asynchronous clock do not mutually
 * disturb one another. Keep the existing 42.5 MHz conversion clock and
 * TIM1 geometry; change only the ADC clock path, not the sampling period.
 * "Asynchronous" names the ADC kernel path, not a different oscillator. */
#define FOC_ADC_CLOCK_SOURCE RCC_ADC12CLKSOURCE_SYSCLK
#define FOC_ADC_CLOCK_PRESCALER ADC_CLOCK_ASYNC_DIV4
#define FOC_ADC_KERNEL_HZ 170000000U
#define FOC_ADC_CLOCK_HZ (FOC_ADC_KERNEL_HZ / 4U)

/* Read-only foreground check. Never reconfigure clocks with ADCs armed.
 * Check PRESC as well as CKMODE: CKMODE=0 alone would accept /1 or /256. */
static inline int FocAdcClock_IsExpected(void)
{
    return HAL_RCC_GetSysClockFreq() == FOC_ADC_KERNEL_HZ &&
        __HAL_RCC_GET_ADC12_SOURCE() == FOC_ADC_CLOCK_SOURCE &&
        (ADC12_COMMON->CCR & (ADC_CCR_CKMODE | ADC_CCR_PRESC)) ==
            FOC_ADC_CLOCK_PRESCALER;
}
#endif
