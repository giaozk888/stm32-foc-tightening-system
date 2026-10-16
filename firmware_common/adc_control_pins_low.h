#ifndef ADC_CONTROL_PINS_LOW_H
#define ADC_CONTROL_PINS_LOW_H

/* Diagnostic ONLY. Keep timer channels/MOE/SD off; no AF restore or unlock.
 * main.h (or the host register model) must be included before this header. */
#if !defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC) || \
    !defined(ZERO_RETEST_BOOT) || !defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC)
#error "Active-low pins require the standalone locked reference diagnostic"
#endif

#define ADC_CONTROL_PC_MASK (GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2)
#define ADC_CONTROL_PB_MASK (GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_13)
#define ADC_CONTROL_PC_MODE_MASK 0x0000003FU
#define ADC_CONTROL_PC_OUTPUT_MODE 0x00000015U
#define ADC_CONTROL_PB_MODE_MASK 0x0C00000FU
#define ADC_CONTROL_PB_OUTPUT_MODE 0x04000005U

static inline void AdcControlPins_HoldLow(void)
{
    HAL_GPIO_WritePin(GPIOC, ADC_CONTROL_PC_MASK, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOB, ADC_CONTROL_PB_MASK, GPIO_PIN_RESET);
    __DSB();
}

static inline void AdcControlPins_InitLow(void)
{
    /* Disable first, preload low BEFORE enabling a GPIO output driver. */
    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
    TIM1->CCER = 0U;
    TIM1->BDTR &= ~(TIM_BDTR_MOE | TIM_BDTR_AOE);
    AdcControlPins_HoldLow();
    GPIO_InitTypeDef gpio = {0};
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    gpio.Pin = ADC_CONTROL_PC_MASK;
    HAL_GPIO_Init(GPIOC, &gpio);
    gpio.Pin = ADC_CONTROL_PB_MASK;
    HAL_GPIO_Init(GPIOB, &gpio);
    __DSB();
}

static inline uint8_t AdcControlPins_ConfigLow(void)
{
    return (GPIOC->MODER & ADC_CONTROL_PC_MODE_MASK) == ADC_CONTROL_PC_OUTPUT_MODE &&
        (GPIOB->MODER & ADC_CONTROL_PB_MODE_MASK) == ADC_CONTROL_PB_OUTPUT_MODE &&
        !(GPIOC->OTYPER & ADC_CONTROL_PC_MASK) && !(GPIOB->OTYPER & ADC_CONTROL_PB_MASK) &&
        !(GPIOC->PUPDR & ADC_CONTROL_PC_MODE_MASK) && !(GPIOB->PUPDR & ADC_CONTROL_PB_MODE_MASK) &&
        !(GPIOC->ODR & ADC_CONTROL_PC_MASK) && !(GPIOB->ODR & ADC_CONTROL_PB_MASK);
}

static inline uint8_t AdcControlPins_LevelLow(void)
{
    return !(GPIOC->IDR & ADC_CONTROL_PC_MASK) && !(GPIOB->IDR & ADC_CONTROL_PB_MASK);
}

#endif
