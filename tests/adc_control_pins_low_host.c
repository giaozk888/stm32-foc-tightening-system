#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct { uint32_t MODER, OTYPER, OSPEEDR, PUPDR, IDR, ODR, AFR[2]; } GPIO_TypeDef;
typedef struct { uint32_t CCER, BDTR; } TIM_TypeDef;
typedef struct { uint32_t Pin, Mode, Pull, Speed; } GPIO_InitTypeDef;
static GPIO_TypeDef b, c;
static TIM_TypeDef tim;
#define GPIOB (&b)
#define GPIOC (&c)
#define TIM1 (&tim)
#define GPIO_PIN_0 1U
#define GPIO_PIN_1 2U
#define GPIO_PIN_2 4U
#define GPIO_PIN_13 (1U << 13)
#define DRIVER_SD_GPIO_Port GPIOC
#define DRIVER_SD_Pin (1U << 6)
#define TIM_BDTR_MOE (1U << 15)
#define TIM_BDTR_AOE (1U << 14)
#define GPIO_PIN_RESET 0U
#define GPIO_MODE_OUTPUT_PP 1U
#define GPIO_NOPULL 0U
#define GPIO_SPEED_FREQ_LOW 0U
#define __DSB() ((void)0)
static unsigned writes, inits;
static void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint32_t pins, uint32_t value)
{
    assert(value == GPIO_PIN_RESET); /* Never issue a high on any control pin. */
    port->ODR &= ~pins;
    ++writes;
}
static void HAL_GPIO_Init(GPIO_TypeDef *port, const GPIO_InitTypeDef *gpio)
{
    assert(!tim.CCER && !(tim.BDTR & (TIM_BDTR_MOE | TIM_BDTR_AOE)));
    assert(!(c.ODR & DRIVER_SD_Pin));
    assert(!(port->ODR & gpio->Pin)); /* Preload before selecting output mode. */
    assert(gpio->Mode == GPIO_MODE_OUTPUT_PP && gpio->Pull == GPIO_NOPULL &&
           gpio->Speed == GPIO_SPEED_FREQ_LOW);
    for (unsigned pin = 0; pin < 16; ++pin) {
        if (!(gpio->Pin & (1U << pin))) continue;
        uint32_t mask = 3U << (2U * pin);
        port->MODER = (port->MODER & ~mask) | (1U << (2U * pin));
        port->PUPDR &= ~mask;
        port->OSPEEDR &= ~mask;
    }
    port->OTYPER &= ~gpio->Pin;
    port->IDR &= ~gpio->Pin; /* Ideal electrical model, not hardware evidence. */
    ++inits;
}
#include "../firmware_common/adc_control_pins_low.h"

int main(void)
{
    memset(&b, 0xff, sizeof(b)); memset(&c, 0xff, sizeof(c));
    tim.CCER = 0xffffU; tim.BDTR = 0xffffffffU;
    GPIO_TypeDef before_b = b, before_c = c;
    AdcControlPins_InitLow();
    assert(writes == 3U && inits == 2U);
    assert(AdcControlPins_ConfigLow() && AdcControlPins_LevelLow());
    assert((b.MODER & ~ADC_CONTROL_PB_MODE_MASK) == (before_b.MODER & ~ADC_CONTROL_PB_MODE_MASK));
    assert((c.MODER & ~ADC_CONTROL_PC_MODE_MASK) == (before_c.MODER & ~ADC_CONTROL_PC_MODE_MASK));
    assert(b.AFR[0] == before_b.AFR[0] && b.AFR[1] == before_b.AFR[1]);
    assert(c.AFR[0] == before_c.AFR[0] && c.AFR[1] == before_c.AFR[1]);
    assert((tim.BDTR & ~(TIM_BDTR_MOE | TIM_BDTR_AOE)) ==
           (0xffffffffU & ~(TIM_BDTR_MOE | TIM_BDTR_AOE)));
    GPIO_TypeDef *ports[] = {GPIOC, GPIOB};
    uint32_t masks[] = {ADC_CONTROL_PC_MASK, ADC_CONTROL_PB_MASK};
    for (unsigned p = 0; p < 2; ++p) {
        GPIO_TypeDef *port = ports[p];
        for (unsigned pin = 0; pin < 16; ++pin) {
            if (!(masks[p] & (1U << pin))) continue;
            GPIO_TypeDef correct = *port;
            port->MODER ^= 1U << (2U * pin);
            assert(!AdcControlPins_ConfigLow());
            AdcControlPins_HoldLow();
            assert(!AdcControlPins_ConfigLow()); /* Do not hide a mode fault. */
            *port = correct; port->OTYPER |= 1U << pin;
            assert(!AdcControlPins_ConfigLow());
            *port = correct; port->PUPDR |= 1U << (2U * pin);
            assert(!AdcControlPins_ConfigLow());
            *port = correct; port->ODR |= 1U << pin;
            assert(!AdcControlPins_ConfigLow());
            *port = correct; port->IDR |= 1U << pin;
            assert(!AdcControlPins_LevelLow());
            *port = correct;
        }
    }
    assert(inits == 2U && AdcControlPins_ConfigLow() && AdcControlPins_LevelLow());
    puts("ACTIVE LOW HOST PASS: preload, six pins, unrelated preservation, fail-closed checks");
}
