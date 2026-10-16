#ifndef FOC_ADC_MOCK_MAIN_H
#define FOC_ADC_MOCK_MAIN_H
#include <stdint.h>
typedef struct { volatile uint32_t CR1, CCR1, CCR2, CCR3, CCR4, CNT, EGR, ARR, PSC, BDTR, CCMR1, CCMR2, CR2, RCR; } TIM_TypeDef;
typedef struct { volatile uint32_t ISR, IER; } ADC_TypeDef;
typedef struct { volatile uint32_t CCR; } ADC_Common_TypeDef;
typedef struct { volatile uint32_t CR, CFGR, PLLCFGR, ICSCR; } RCC_TypeDef;
extern RCC_TypeDef mock_rcc;
#define RCC (&mock_rcc)
typedef struct { volatile uint32_t CTRL, CYCCNT; } DWT_Type;
extern TIM_TypeDef mock_tim;
extern ADC_TypeDef mock_adc1, mock_adc2;
extern DWT_Type mock_dwt;
extern uint32_t mock_primask;
extern uint32_t mock_ipsr;
extern ADC_Common_TypeDef mock_adc_common;
extern uint32_t mock_hclk;
extern uint32_t mock_frequency_reads;
extern uint32_t mock_sysclk, mock_adc_clock_source;
#define TIM1 (&mock_tim)
#define ADC1 (&mock_adc1)
#define ADC2 (&mock_adc2)
#define DWT (&mock_dwt)
#define ADC12_COMMON (&mock_adc_common)
#define TIM_CR1_CEN 1U
#define TIM_CR1_UDIS 2U
#define TIM_CR1_DIR (1U << 4)
#define TIM_CR1_CMS (3U << 5)
#define TIM_CR1_CKD (3U << 8)
#define TIM_COUNTERMODE_CENTERALIGNED1 (1U << 5)
#define TIM_BDTR_DTG 255U
#define TIM_CCMR1_OC1PE (1U << 3)
#define TIM_CCMR1_OC2PE (1U << 11)
#define TIM_CCMR2_OC3PE (1U << 3)
#define TIM_CCMR2_OC4PE (1U << 11)
#define TIM_CR2_MMS2 (15U << 20)
#define TIM_TRGO2_OC4REF (7U << 20)
#define ADC_CCR_CKMODE (3U << 16)
#define ADC_CCR_PRESC (15U << 18)
#define ADC_CLOCK_SYNC_PCLK_DIV4 (3U << 16)
#define ADC_CLOCK_ASYNC_DIV4 (2U << 18)
#define RCC_ADC12CLKSOURCE_SYSCLK (2U << 28)
#define __HAL_RCC_GET_ADC12_SOURCE() (mock_adc_clock_source)
#define TIM_EGR_UG 1U
#define ADC_ISR_JEOS (1U << 6)
#define DWT_CTRL_CYCCNTENA_Msk 1U
static inline uint32_t __get_PRIMASK(void) { return mock_primask; }
static inline uint32_t __get_IPSR(void) { return mock_ipsr; }
static inline void __disable_irq(void) { mock_primask = 1; }
static inline void __set_PRIMASK(uint32_t x) { mock_primask = x; }
static inline void __DMB(void) {}
static inline uint32_t HAL_RCC_GetHCLKFreq(void) { ++mock_frequency_reads; return mock_hclk; }
static inline uint32_t HAL_RCC_GetSysClockFreq(void) { ++mock_frequency_reads; return mock_sysclk; }
static inline uint32_t HAL_RCC_GetPCLK2Freq(void) { ++mock_frequency_reads; return mock_hclk; }
#endif
