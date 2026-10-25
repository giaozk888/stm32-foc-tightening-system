#ifndef FOC_ADC_STATISTICS_TASK_H
#define FOC_ADC_STATISTICS_TASK_H
#ifdef __cplusplus
extern "C" {
#endif
/* Startup task only; no heap allocation, diagnostics only. Start before ADC IRQ. */
int FocAdcStatisticsTask_Start(void);
#ifdef __cplusplus
}
#endif
#endif
