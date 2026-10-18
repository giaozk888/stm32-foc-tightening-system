/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    stm32g4xx_it.c
  * @brief   Interrupt Service Routines.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "foc_hot_path.h"
#include "foc_fast_path_profile.h"
#include "foc_preempt_probe.h"
#if defined(FOC_ADC_WINDOW)
#include "foc_adc_timing_stm32.h"
#endif
#include "stm32g4xx_it.h"
/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN TD */

/* USER CODE END TD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
extern volatile uint8_t g_rtos_started;
extern void xPortSysTickHandler(void);
extern UART_HandleTypeDef hlpuart1;
#if defined(FOC_PROTECTED_CLOSED_LOOP)
#include "protected_closed_loop.h"
#define SWITCH_FAULT_OFF() ProtectedLoop_EmergencyOff(CL_CORE_FAULT)
#elif defined(FOC_FEEDBACK_SAFETY_BINDING)
#include "foc_feedback_binding_stm32.h"
#define SWITCH_FAULT_OFF() FocFeedbackBinding_EmergencyOff(FOC_FB_CORE_FAULT)
#elif defined(SWITCH_FEEDBACK_DIAGNOSTIC)
extern void SwitchFeedback_EmergencyOff(uint32_t reason);
#define SWITCH_FAULT_OFF() SwitchFeedback_EmergencyOff(9U)
#else
#define SWITCH_FAULT_OFF() ((void)0)
#endif
/* USER CODE END 0 */

/* External variables --------------------------------------------------------*/
extern ADC_HandleTypeDef hadc1;
extern ADC_HandleTypeDef hadc2;
/* USER CODE BEGIN EV */

/* USER CODE END EV */

/******************************************************************************/
/*           Cortex-M4 Processor Interruption and Exception Handlers          */
/******************************************************************************/
/**
  * @brief This function handles Non maskable interrupt.
  */
void NMI_Handler(void)
{
  SWITCH_FAULT_OFF();
  /* USER CODE BEGIN NonMaskableInt_IRQn 0 */

  /* USER CODE END NonMaskableInt_IRQn 0 */
  /* USER CODE BEGIN NonMaskableInt_IRQn 1 */
   while (1)
  {
  }
  /* USER CODE END NonMaskableInt_IRQn 1 */
}

/**
  * @brief This function handles Hard fault interrupt.
  */
void HardFault_Handler(void)
{
  SWITCH_FAULT_OFF();
  /* USER CODE BEGIN HardFault_IRQn 0 */

  /* USER CODE END HardFault_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_HardFault_IRQn 0 */
    /* USER CODE END W1_HardFault_IRQn 0 */
  }
}

/**
  * @brief This function handles Memory management fault.
  */
void MemManage_Handler(void)
{
  SWITCH_FAULT_OFF();
  /* USER CODE BEGIN MemoryManagement_IRQn 0 */

  /* USER CODE END MemoryManagement_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_MemoryManagement_IRQn 0 */
    /* USER CODE END W1_MemoryManagement_IRQn 0 */
  }
}

/**
  * @brief This function handles Prefetch fault, memory access fault.
  */
void BusFault_Handler(void)
{
  SWITCH_FAULT_OFF();
  /* USER CODE BEGIN BusFault_IRQn 0 */

  /* USER CODE END BusFault_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_BusFault_IRQn 0 */
    /* USER CODE END W1_BusFault_IRQn 0 */
  }
}

/**
  * @brief This function handles Undefined instruction or illegal state.
  */
void UsageFault_Handler(void)
{
  SWITCH_FAULT_OFF();
  /* USER CODE BEGIN UsageFault_IRQn 0 */

  /* USER CODE END UsageFault_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_UsageFault_IRQn 0 */
    /* USER CODE END W1_UsageFault_IRQn 0 */
  }
}

/**
  * @brief This function handles System service call via SWI instruction.
  */

/**
  * @brief This function handles Debug monitor.
  */
void DebugMon_Handler(void)
{
  /* USER CODE BEGIN DebugMonitor_IRQn 0 */

  /* USER CODE END DebugMonitor_IRQn 0 */
  /* USER CODE BEGIN DebugMonitor_IRQn 1 */

  /* USER CODE END DebugMonitor_IRQn 1 */
}

/**
  * @brief This function handles Pendable request for system service.
  */


/**
  * @brief This function handles System tick timer.
  */
void SysTick_Handler(void)
{
  /* USER CODE BEGIN SysTick_IRQn 0 */

  /* USER CODE END SysTick_IRQn 0 */
  HAL_IncTick();
  /* USER CODE BEGIN SysTick_IRQn 1 */
if (g_rtos_started != 0U)
    {
        xPortSysTickHandler();
    }
  /* USER CODE END SysTick_IRQn 1 */
}

/******************************************************************************/
/* STM32G4xx Peripheral Interrupt Handlers                                    */
/* Add here the Interrupt Handlers for the used peripherals.                  */
/* For the available peripheral interrupt handler names,                      */
/* please refer to the startup file (startup_stm32g4xx.s).                    */
/******************************************************************************/

/**
  * @brief This function handles ADC1 and ADC2 global interrupt.
  */
FOC_RAM_PATH void ADC1_2_IRQHandler(void)
{
#if defined(FOC_FAST_CURRENT_REJECT)
#if defined(FOC_PREEMPT_COMMIT_PROBE)
  uint32_t current_profile_start=FocPreempt_Begin();
#else
  uint32_t current_profile_start=DWT->CYCCNT;
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
  ProtectedLoop_PwmEntry(); /* First control action, before ADC read/math. */
#endif
  FocProfile_Begin();
#endif
  /* USER CODE BEGIN ADC1_2_IRQn 0 */

  /* USER CODE END ADC1_2_IRQn 0 */
#if defined(FOC_ADC_WINDOW)
  uint32_t timing_start = FocAdcTiming_IrqEnter();
#endif
#if defined(FOC_PROTECTED_CLOSED_LOOP)
  ProtectedLoop_AdcIrq();
  FocAdcTiming_IrqExit(timing_start);
#if defined(FOC_FAST_CURRENT_REJECT)
  ProtectedLoop_AdcProfileEnd(current_profile_start);
#endif
#else
  HAL_ADC_IRQHandler(&hadc1);
#if defined(FOC_ADC_WINDOW)
  /* ADC2 has no completion IRQ. Keep HAL servicing if another ADC2 interrupt
   * source is explicitly enabled; do not suppress watchdog/error interrupts. */
  if ((hadc2.Instance->ISR & hadc2.Instance->IER) != 0U)
      HAL_ADC_IRQHandler(&hadc2);
  FocAdcTiming_IrqExit(timing_start);
#else
  HAL_ADC_IRQHandler(&hadc2);
#endif
#endif
  /* USER CODE BEGIN ADC1_2_IRQn 1 */

  /* USER CODE END ADC1_2_IRQn 1 */
}

/* USER CODE BEGIN 1 */
void LPUART1_IRQHandler(void)
{
    HAL_UART_IRQHandler(&hlpuart1);
}
/* USER CODE END 1 */
