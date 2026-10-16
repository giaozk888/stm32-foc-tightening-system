#ifndef ADC_DMA_MOCK_MAIN_H
#define ADC_DMA_MOCK_MAIN_H
#include <stdint.h>
typedef enum { HAL_OK, HAL_ERROR } HAL_StatusTypeDef;
typedef struct { uint32_t CR1, CR2, CNT, PSC, ARR, CCR4, CCER, BDTR; } TIM_TypeDef;
typedef struct { uint32_t ODR, BSRR; } GPIO_TypeDef;
typedef struct { uint32_t CR, ISR, SQR1, SQR2, SQR3, SQR4, SMPR1, SMPR2; } ADC_TypeDef;
typedef struct { uint32_t CCR; } ADC_Common_TypeDef;
typedef struct { uint32_t CCR, CNDTR; } DMA_Channel_TypeDef;
typedef struct { uint32_t Request, Direction, PeriphInc, MemInc, PeriphDataAlignment,
    MemDataAlignment, Mode, Priority; } DMA_InitTypeDef;
typedef struct { DMA_Channel_TypeDef *Instance; DMA_InitTypeDef Init; void *Parent; } DMA_HandleTypeDef;
typedef struct { uint32_t ScanConvMode, EOCSelection, LowPowerAutoWait, ContinuousConvMode,
    NbrOfConversion, DiscontinuousConvMode, ExternalTrigConv, ExternalTrigConvEdge,
    DMAContinuousRequests, Overrun, OversamplingMode, ClockPrescaler; } ADC_InitTypeDef;
typedef struct { ADC_TypeDef *Instance; ADC_InitTypeDef Init; DMA_HandleTypeDef *DMA_Handle;
    uint32_t ErrorCode; } ADC_HandleTypeDef;
typedef struct { uint32_t Channel, Rank, SamplingTime, SingleDiff, OffsetNumber; } ADC_ChannelConfTypeDef;
extern TIM_TypeDef mock_tim;
extern GPIO_TypeDef mock_gpio;
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
typedef unsigned IRQn_Type;
typedef struct { uint32_t PeriphClockSelection, Adc345ClockSelection; } RCC_PeriphCLKInitTypeDef;
typedef struct { uint32_t Pin, Mode, Pull; } GPIO_InitTypeDef;
extern ADC_TypeDef mock_adc[3];
extern ADC_Common_TypeDef mock_common345;
extern DMA_Channel_TypeDef mock_dma[3];
#define ADC5 (&mock_adc[2])
#define ADC345_COMMON (&mock_common345)
#define DMA2_Channel1 (&mock_dma[2])
#define DMA2_Channel1_IRQn 21U
#define ADC5_IRQn 25U
#define DMA_REQUEST_ADC5 39U
#define FOC_ADC_CLOCK_PRESCALER 0x80000U
#define RCC_PERIPHCLK_ADC345 345U
#define RCC_ADC345CLKSOURCE_SYSCLK 2U
#define __HAL_RCC_GET_ADC345_SOURCE() mock_clock345
extern uint32_t mock_clock345;
#define __HAL_RCC_DMA2_CLK_ENABLE() ((void)0)
#define __HAL_RCC_ADC345_CLK_ENABLE() ((void)0)
#define __HAL_RCC_GPIOA_CLK_ENABLE() ((void)0)
#define GPIOA (&mock_gpio)
#define GPIO_PIN_8 256U
#define GPIO_MODE_ANALOG 3U
#define GPIO_NOPULL 0U
#define ADC_CCR_CKMODE 0x30000U
#define ADC_CCR_PRESC 0x3C0000U
HAL_StatusTypeDef HAL_RCCEx_PeriphCLKConfig(RCC_PeriphCLKInitTypeDef *);
void HAL_GPIO_Init(GPIO_TypeDef *, GPIO_InitTypeDef *);
HAL_StatusTypeDef HAL_ADCEx_Calibration_Start(ADC_HandleTypeDef *, uint32_t);
void HAL_ADC_IRQHandler(ADC_HandleTypeDef *);
#else
extern ADC_TypeDef mock_adc[2];
extern DMA_Channel_TypeDef mock_dma[2];
#endif
extern ADC_Common_TypeDef mock_common;
#define TIM1 (&mock_tim)
#define ADC1 (&mock_adc[0])
#define ADC2 (&mock_adc[1])
#define ADC12_COMMON (&mock_common)
#define DMA1_Channel3 (&mock_dma[0])
#define DMA1_Channel4 (&mock_dma[1])
#define DRIVER_SD_GPIO_Port (&mock_gpio)
#define DRIVER_SD_Pin 64U
#define TIM_CR1_CEN 1U
#define TIM_CR1_DIR 16U
#define TIM_BDTR_MOE 32768U
#define TIM_BDTR_AOE 16384U
#define ADC_CR_ADSTART 4U
#define ADC_CR_JADSTART 8U
#define DMA_CCR_EN 1U
#define ADC_CCR_DUAL 31U
#define TIM_CR2_MMS2 0xF00000U
#define TIM_TRGO2_OC4REF 0x700000U
#define ADC_SCAN_DISABLE 0U
#define ADC_SCAN_ENABLE 1U
#define ADC_EOC_SINGLE_CONV 1U
#define DISABLE 0U
#define ENABLE 1U
#define ADC_EXTERNALTRIG_T1_TRGO2 17U
#define ADC_EXTERNALTRIGCONVEDGE_RISING 1U
#define ADC_OVR_DATA_PRESERVED 0U
#define ADC_CHANNEL_1 1U
#define ADC_CHANNEL_2 2U
#define ADC_CHANNEL_9 9U
#define ADC_REGULAR_RANK_1 1U
#define ADC_REGULAR_RANK_2 2U
#define ADC_SAMPLETIME_12CYCLES_5 12U
#define ADC_SAMPLETIME_247CYCLES_5 247U
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
static inline uint32_t LL_ADC_GetChannelSamplingTime(ADC_TypeDef *adc, uint32_t channel)
{ (void)channel; return adc->SMPR1; }
#endif
#define ADC_SINGLE_ENDED 0U
#define ADC_OFFSET_NONE 0U
#define DMA_REQUEST_ADC1 5U
#define DMA_REQUEST_ADC2 36U
#define DMA_PERIPH_TO_MEMORY 0U
#define DMA_PINC_DISABLE 0U
#define DMA_MINC_ENABLE 1U
#define DMA_PDATAALIGN_HALFWORD 2U
#define DMA_MDATAALIGN_HALFWORD 2U
#define DMA_NORMAL 0U
#define DMA_PRIORITY_HIGH 2U
#define DMA1_Channel3_IRQn 3U
#define DMA1_Channel4_IRQn 4U
#define DMA_IT_HT 4U
#define DMA_IT_TC 2U
#define DMA_IT_TE 8U
#define ADC_FLAG_OVR 16U
#define HAL_ADC_ERROR_OVR 2U
#define __HAL_RCC_DMA1_CLK_ENABLE() ((void)0)
#define __HAL_RCC_DMAMUX1_CLK_ENABLE() ((void)0)
#define __HAL_DMA_DISABLE_IT(d,b) ((d)->Instance->CCR &= ~(b))
#define __HAL_DMA_DISABLE(d) ((d)->Instance->CCR &= ~DMA_CCR_EN)
#define __HAL_DMA_GET_COUNTER(d) ((d)->Instance->CNDTR)
#define __DMB() ((void)0)
#define __DSB() ((void)0)
#define __get_PRIMASK() 0U
#define __disable_irq() ((void)0)
#define __set_PRIMASK(x) ((void)(x))
HAL_StatusTypeDef HAL_ADC_Init(ADC_HandleTypeDef *);
HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef *, const ADC_ChannelConfTypeDef *);
HAL_StatusTypeDef HAL_DMA_Init(DMA_HandleTypeDef *);
HAL_StatusTypeDef HAL_ADC_Start_DMA(ADC_HandleTypeDef *, uint32_t *, uint32_t);
HAL_StatusTypeDef HAL_ADC_Stop_DMA(ADC_HandleTypeDef *);
HAL_StatusTypeDef HAL_ADC_Stop(ADC_HandleTypeDef *);
HAL_StatusTypeDef HAL_ADCEx_InjectedStop_IT(ADC_HandleTypeDef *);
HAL_StatusTypeDef HAL_ADCEx_InjectedStop(ADC_HandleTypeDef *);
HAL_StatusTypeDef HAL_ADCEx_InjectedStart(ADC_HandleTypeDef *);
HAL_StatusTypeDef HAL_ADCEx_InjectedStart_IT(ADC_HandleTypeDef *);
uint32_t HAL_ADC_GetError(ADC_HandleTypeDef *);
void HAL_DMA_IRQHandler(DMA_HandleTypeDef *);
void HAL_NVIC_SetPriority(unsigned, unsigned, unsigned);
void HAL_NVIC_ClearPendingIRQ(unsigned);
void HAL_NVIC_EnableIRQ(unsigned);
void HAL_NVIC_DisableIRQ(unsigned);
#endif
