#include "foc_adc_statistics_task.h"
#include "foc_adc_timing_stm32.h"
#include "FreeRTOS.h"
#include "task.h"
#include "foc_hot_path.h"

#define ADC_STATS_STACK_WORDS 512U
static StaticTask_t statistics_tcb;
static StackType_t statistics_stack[ADC_STATS_STACK_WORDS];
static TaskHandle_t statistics_task;

static void StatisticsTask(void *unused)
{
    (void)unused;
#if defined(FOC_IRQ_COMPACT)
    unsigned stack_scan_wake = 0U;
#endif
    for (;;) {
        /* At most two completed buffers per wake, no unbounded drain loop. */
        (void)FocAdcTiming_ProcessRawOne();
        (void)FocAdcTiming_ProcessRawOne();
#if defined(FOC_IRQ_COMPACT)
        /* Watermark is retained by the stack fill pattern. Scan on the first
         * wake and every 64 wakes, rather than walk 512 words every wake.
         * Diagnostic freshness only: never a control/guardian input. */
        if (stack_scan_wake++ % 64U == 0U)
#endif
            FocAdcTiming_NoteWorkerStack((uint32_t)uxTaskGetStackHighWaterMark(NULL) * sizeof(StackType_t));
        TickType_t delay = pdMS_TO_TICKS(1U);
        vTaskDelay(delay != 0U ? delay : 1U);
    }
}
int FocAdcStatisticsTask_Start(void)
{
    if (statistics_task != NULL) return 1;
    /* Priority 1: below 1kHz MotorControl(4), Tightening(3), Router/Protocol(2).
     * The ISR never calls the RTOS or waits for this optional diagnostic owner. */
    statistics_task = xTaskCreateStatic(StatisticsTask, "AdcStats", ADC_STATS_STACK_WORDS,
                                       NULL, 1U, statistics_stack, &statistics_tcb);
    return statistics_task != NULL;
}
