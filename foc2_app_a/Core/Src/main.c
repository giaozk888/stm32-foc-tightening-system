/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
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
#include "App/config/app_includes.inc"
#include "App/config/app_types.inc"
#include "App/config/app_config.inc"
#include "App/state/app_state.inc"
#include "App/internal/app_declarations.inc"
#include "App/protocol/uart_transport.inc"
#include "App/control/motor_service.inc"
#include "App/application/tightening_results.inc"
#include "App/protocol/session_events.inc"
#include "App/storage/recipe_storage.inc"
#include "App/storage/boot_update.inc"
#include "App/protocol/command_dispatch.inc"
#include "App/protocol/router_protocol_tasks.inc"
#include "App/application/tightening_task.inc"
#include "App/diagnostics/health_monitor_tasks.inc"
#include "App/sensing/encoder_service.inc"
#include "App/diagnostics/value_format.inc"
#include "App/control/power_current_loop.inc"
#include "App/control/outer_loop.inc"
#include "App/sensing/pwm_adc_service.inc"
#include "App/sensing/adc_irq_binding.inc"
#include "App/startup/startup_task.inc"
/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */
  EncoderDiag_InitCycleCounter();
  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_TIM1_Init();
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
  AdcControlPins_InitLow(); /* Diagnostic only, before ADC/tasks; never restore AF. */
#endif
  MX_SPI1_Init();
#if defined(AS5047P_SPI_DMA)
  if (!AS5047P_DmaInit(EncoderDma_FaultFromISR))
  {
      PowerStage_Disable();
      Error_Handler();
  }
#endif
  MX_LPUART1_UART_Init();
  MX_ADC1_Init();
  MX_ADC2_Init();
  /* USER CODE BEGIN 2 */

#if defined(CAN_LINK_PROBE_ONLY)
    /* This build never starts TIM1 PWM, ADC injected conversions, FreeRTOS,
     * motor-control tasks or the bridge. PC6 is forced low before CAN runs. */
    PowerStage_Disable();
    CAN_LinkProbe_RunForever(&hlpuart1);
#endif

    /* USER button selects a one-boot, discovery-only safety path. */
    g_safe_comm_boot = SafeCommBootRequested();

    /*
     * Start FreeRTOS BEFORE running any startup helper that uses HAL_Delay().
     * StartupTask performs ADC calibration, encoder check, TIM1/ADC bring-up,
     * and then creates MotorControlTask, TighteningTask and MonitorTask.
     */
    PowerStage_Disable();

    UART_SendLiteral(
        "\r\n"
        "Creating FreeRTOS StartupTask...\r\n"
        "Power stage remains DISABLED\r\n");

    if (xTaskCreate(StartupTask,
                    "Startup",
                    768U,
                    NULL,
                    5U,
                    NULL) != pdPASS)
    {
        UART_SendLiteral("StartupTask CREATE FAILED\r\n");
        Error_Handler();
    }

    UART_SendLiteral("Starting scheduler...\r\n");

    vTaskStartScheduler();

    /* A correctly running scheduler never returns here. */
    UART_SendLiteral("ERROR: scheduler returned\r\n");
    PowerStage_Disable();
    PWM_StopAll();
    Error_Handler();

    /* No legacy motor demo after scheduler failure. */
  /* USER CODE END 2 */

  /* Fail-closed fallback if Error_Handler is ever changed to return. */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */
    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/* APP_BOARD_DEFINITIONS_MOVED_TO_APP_BOARD_C */

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_EmergencyOff(CL_CORE_FAULT);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_EmergencyOff(FOC_FB_CORE_FAULT);
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
    SwitchFeedback_EmergencyOff(9U);
#endif
  /* USER CODE BEGIN Error_Handler_Debug */
/* Best-effort safe shutdown before halting. */
HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
__disable_irq();
while (1)
{
}
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
