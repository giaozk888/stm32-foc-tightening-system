#ifndef APP_A_BOARD_H
#define APP_A_BOARD_H
#include "main.h"
/* Handles are still defined once in state/app_state.inc. */
extern ADC_HandleTypeDef hadc1,hadc2;
extern UART_HandleTypeDef hlpuart1;
extern SPI_HandleTypeDef hspi1;
extern TIM_HandleTypeDef htim1;
void SystemClock_Config(void);
void MX_GPIO_Init(void);
void MX_TIM1_Init(void);
void MX_SPI1_Init(void);
void MX_LPUART1_UART_Init(void);
void MX_ADC1_Init(void);
void MX_ADC2_Init(void);
#endif
