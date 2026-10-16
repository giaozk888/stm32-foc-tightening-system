/* Execute the real worker with a tiny RTOS mock; no simulated ADC hardware. */
#include "FreeRTOS.h"
#include "task.h"
#include "foc_adc_statistics_task.h"
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
static jmp_buf task_return;
static void (*task_entry)(void *);
static unsigned creates, processes, stack_checks, delays;
static uint32_t free_bytes;
static int create_failure = 1;

TaskHandle_t xTaskCreateStatic(void (*entry)(void *), const char *name,
    uint32_t depth, void *argument, UBaseType_t priority,
    StackType_t *stack, StaticTask_t *tcb)
{
    ++creates;
    assert(strcmp(name, "AdcStats") == 0 && depth == 512 && priority == 1);
    assert(argument == NULL && stack != NULL && tcb != NULL);
    task_entry = entry;
    return create_failure ? NULL : tcb;
}
UBaseType_t uxTaskGetStackHighWaterMark(TaskHandle_t task)
{
    assert(task == NULL);
    ++stack_checks;
    return 425;
}
int FocAdcTiming_ProcessRawOne(void)
{
    ++processes;
    return 1;
}
void FocAdcTiming_NoteWorkerStack(uint32_t bytes)
{
    free_bytes = bytes;
}
void vTaskDelay(TickType_t ticks)
{
    assert(ticks >= 1);
    ++delays;
#if defined(FOC_IRQ_COMPACT)
    if (delays < 130U) return;
#endif
    longjmp(task_return, 1); /* End this bounded wake after its RTOS yield. */
}
int main(void)
{
    assert(!FocAdcStatisticsTask_Start() && creates == 1);
    create_failure = 0;
    assert(FocAdcStatisticsTask_Start() && creates == 2);
    assert(FocAdcStatisticsTask_Start() && creates == 2);
    if (setjmp(task_return) == 0) task_entry(NULL);
#if defined(FOC_IRQ_COMPACT)
    assert(processes == 260 && stack_checks == 3 && delays == 130 && free_bytes == 1700);
#else
    assert(processes == 2 && stack_checks == 1 && delays == 1 && free_bytes == 1700);
#endif
    puts("PASS: actual static RTOS worker, create failure/retry/idempotence, two-block budget/stack units/yield");
    return 0;
}
