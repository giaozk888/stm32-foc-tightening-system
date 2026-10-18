#ifndef FOC_PREEMPT_MOCK_MAIN_H
#define FOC_PREEMPT_MOCK_MAIN_H
#include "../foc_adc_mock/main.h"
typedef struct { volatile uint32_t ODR,BSRR; } ProbeGpio;
extern ProbeGpio mock_gpio;
#define DRIVER_SD_GPIO_Port (&mock_gpio)
#define DRIVER_SD_Pin (1U<<6)
#define TIM_BDTR_MOE (1U<<15)
#define TIM_BDTR_AOE (1U<<14)
typedef int IRQn_Type;
enum { TIM7_DAC_IRQn=55,TIM2_IRQn=28,DMA1_Channel4_IRQn=14,
       DMA1_Channel5_IRQn=15,ADC1_2_IRQn=18,SysTick_IRQn=-1,
       PendSV_IRQn=-2,FMAC_IRQn=101,TIM6_DAC_IRQn=54 };
extern uint32_t mock_priority[104],mock_enabled[104],mock_group;
static inline uint32_t NVIC_GetPriority(IRQn_Type id) { return mock_priority[id+2]; }
static inline uint32_t NVIC_GetEnableIRQ(IRQn_Type id) { return mock_enabled[id+2]; }
static inline uint32_t NVIC_GetPriorityGrouping(void) { return mock_group; }
void mock_barrier(void);
#if defined(FOC_PRE_CAPTURE_TEST)
void mock_capture_point(unsigned point);
#define FOC_PRE_CAPTURE_TEST_POINT(point) mock_capture_point(point)
#endif
#define __DMB() mock_barrier()
#endif
