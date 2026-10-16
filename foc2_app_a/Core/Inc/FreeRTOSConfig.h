#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

/* ============================================================
 * FreeRTOS V11.3.1 configuration
 * MCU: STM32G474RET6
 * CPU: Cortex-M4F @ 170 MHz
 * Compiler: arm-none-eabi-gcc
 * Port: portable/GCC/ARM_CM4F
 * ============================================================ */

/* ---------------- Basic scheduler ---------------- */

#define configUSE_PREEMPTION                    1
#define configUSE_TIME_SLICING                  1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1

/* FreeRTOS system tick: 1 kHz = 1 ms */
#define configCPU_CLOCK_HZ                      170000000UL
#define configTICK_RATE_HZ                      1000U

/*
 * Priority range:
 *
 * 0 = lowest
 * 7 = highest task priority
 *
 * NOTE:
 * Task priority and NVIC interrupt priority are two different systems.
 */
#define configMAX_PRIORITIES                    8

/*
 * Cortex-M4 stack unit = StackType_t = 32 bits.
 *
 * 128 means:
 * 128 words x 4 bytes = 512 bytes.
 */
#define configMINIMAL_STACK_SIZE                128U
#define configMAX_TASK_NAME_LEN                 16U

/* FreeRTOS V11: use a 32-bit tick counter. */
#define configTICK_TYPE_WIDTH_IN_BITS           TICK_TYPE_WIDTH_32_BITS

#define configIDLE_SHOULD_YIELD                 1
#define configUSE_TICKLESS_IDLE                 0

/* ---------------- Memory ---------------- */

/*
 * The ESP transport, Router, protocol queues and motor tasks are allocated
 * from heap_4. The 32 KiB setting left only 240 bytes before BootHealthTask
 * was created in the Stage 10.8 A-slot trial, so reserve 8 KiB more here.
 * The linker still enforces the 0x1FFC0-byte SRAM boundary/mailbox reserve.
 */
#define configSUPPORT_STATIC_ALLOCATION         1
#define configKERNEL_PROVIDED_STATIC_MEMORY     1
#define configSUPPORT_DYNAMIC_ALLOCATION        1
#define configTOTAL_HEAP_SIZE                   (40U * 1024U)

#define configAPPLICATION_ALLOCATED_HEAP        0

/* ---------------- Task features ---------------- */

#define configUSE_TASK_NOTIFICATIONS            1
#define configTASK_NOTIFICATION_ARRAY_ENTRIES   1

#define configUSE_MUTEXES                       1
#define configUSE_RECURSIVE_MUTEXES             1
#define configUSE_COUNTING_SEMAPHORES           1
#define configUSE_QUEUE_SETS                    0

#define configQUEUE_REGISTRY_SIZE               8

/* ---------------- Software timers ---------------- */

/*
 * First FreeRTOS bring-up does not need software timers.
 * vTaskDelay/vTaskDelayUntil do NOT require configUSE_TIMERS.
 */
#define configUSE_TIMERS                        0

/* ---------------- Event/stream features ---------------- */

#define configUSE_EVENT_GROUPS                  1
#define configUSE_STREAM_BUFFERS                1

/* ---------------- Hooks / diagnostics ---------------- */

#define configUSE_IDLE_HOOK                     0
#define configUSE_TICK_HOOK                     0
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
#define configUSE_MALLOC_FAILED_HOOK            1
#define configCHECK_FOR_STACK_OVERFLOW          2
#else
#define configUSE_MALLOC_FAILED_HOOK            0
#define configCHECK_FOR_STACK_OVERFLOW          0
#endif

/*
 * We will enable stack overflow and malloc-failure hooks
 * after the kernel is running correctly.
 */

#define configUSE_TRACE_FACILITY                0
#define configUSE_STATS_FORMATTING_FUNCTIONS    0
#define configGENERATE_RUN_TIME_STATS           0

#define configUSE_NEWLIB_REENTRANT              0

/* ---------------- Co-routines ---------------- */

#define configUSE_CO_ROUTINES                   0
#define configMAX_CO_ROUTINE_PRIORITIES         2

/* ---------------- Cortex-M4 interrupt priorities ---------------- */

/*
 * STM32G4 implements 4 NVIC priority bits:
 *
 * priority 0  = highest urgency
 * priority 15 = lowest urgency
 */
#define configPRIO_BITS                         4

#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY 15

/*
 * Interrupts with NVIC priority numerically >= 5 may call
 * FreeRTOS ...FromISR() APIs.
 *
 * Interrupts with priority 0..4 must NOT call FreeRTOS APIs.
 *
 * Later our 20 kHz FOC interrupt can stay in this high-priority
 * group and remain independent from RTOS scheduling.
 */
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY 5

#define configKERNEL_INTERRUPT_PRIORITY         \
    ( configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8U - configPRIO_BITS) )

#define configMAX_SYSCALL_INTERRUPT_PRIORITY    \
    ( configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8U - configPRIO_BITS) )

#define configMAX_API_CALL_INTERRUPT_PRIORITY   \
    configMAX_SYSCALL_INTERRUPT_PRIORITY

/* ---------------- API inclusion ---------------- */

#define INCLUDE_vTaskPrioritySet                1
#define INCLUDE_uxTaskPriorityGet               1
#define INCLUDE_vTaskDelete                     1
#define INCLUDE_vTaskSuspend                    1

#define INCLUDE_vTaskDelay                      1
#define INCLUDE_vTaskDelayUntil                 1

#define INCLUDE_xTaskGetSchedulerState          1
#define INCLUDE_xTaskGetCurrentTaskHandle       1
#define INCLUDE_uxTaskGetStackHighWaterMark     1

#define INCLUDE_xTaskAbortDelay                 1
#define INCLUDE_xTaskGetIdleTaskHandle          1

/* ---------------- Assertions ---------------- */
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
#ifdef __cplusplus
extern "C" {
#endif
extern void SwitchFeedback_EmergencyOff(uint32_t reason);
#ifdef __cplusplus
}
#endif
#define DIAGNOSTIC_ASSERT_OFF() SwitchFeedback_EmergencyOff(9U)
#else
#define DIAGNOSTIC_ASSERT_OFF() ((void)0)
#endif

#define configASSERT(x)                         \
    do                                          \
    {                                           \
        if ((x) == 0)                           \
        {                                       \
            DIAGNOSTIC_ASSERT_OFF();             \
            taskDISABLE_INTERRUPTS();           \
            for (;;)                            \
            {                                   \
            }                                   \
        }                                       \
    } while (0)

/*
 * ARM_CM4F port exception-handler mapping.
 *
 * IMPORTANT:
 * We intentionally do NOT map xPortSysTickHandler to SysTick_Handler here.
 *
 * Your current STM32 HAL also uses SysTick. In a later step we will make
 * SysTick_Handler call both HAL_IncTick() and FreeRTOS xPortSysTickHandler().
 *
 * SVC and PendSV will be owned by FreeRTOS.
 */
#define vPortSVCHandler                         SVC_Handler
#define xPortPendSVHandler                      PendSV_Handler

#endif /* FREERTOS_CONFIG_H */
