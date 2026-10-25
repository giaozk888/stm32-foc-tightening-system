#ifndef ADC_DMA_DIAG_H
#define ADC_DMA_DIAG_H
#include "main.h"

/* Fixed, non-circular capture: foreground reads only after both DMA writers
 * are stopped. No filtering, zero-offset publication, or FOC qualification. */
#if defined(ADC_DMA_REFERENCE_DOUBLE_CAPTURE)
#if !defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC) || !defined(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC) || \
    !defined(ADC_DMA_ADC12_ONLY_DIAGNOSTIC) || !defined(ADC_DMA_PARALLEL_LONG_SAMPLE) || \
    !defined(ADC_DMA_PARALLEL_DIAGNOSTIC) || !defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC) || \
    !defined(ADC_DMA_RAW_DIAGNOSTIC) || !defined(ZERO_RETEST_BOOT)
#error "Double capture requires the GPIO-low locked ADC1/2 reference profile"
#endif
enum { ADC_DMA_DIAG_PAIRS = 8192U, ADC_DMA_DIAG_TIMEOUT_MS = 1000U };
#else
enum { ADC_DMA_DIAG_PAIRS = 4096U, ADC_DMA_DIAG_TIMEOUT_MS = 1000U };
#endif
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC) && !defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
enum { ADC_DMA_DIAG_U_STRIDE = 2U };
#else
enum { ADC_DMA_DIAG_U_STRIDE = 1U };
#endif
enum { ADC_DMA_DIAG_IDLE, ADC_DMA_DIAG_ARMING, ADC_DMA_DIAG_RUNNING,
       ADC_DMA_DIAG_STOPPING, ADC_DMA_DIAG_READY, ADC_DMA_DIAG_FAILED };
enum { ADC_DMA_DIAG_OK, ADC_DMA_DIAG_CONFIG, ADC_DMA_DIAG_ADC_ERROR,
       ADC_DMA_DIAG_UNSAFE, ADC_DMA_DIAG_TIMEOUT, ADC_DMA_DIAG_STOP_ERROR,
       ADC_DMA_DIAG_COUNT_ERROR };
typedef struct {
    uint32_t state, reason, count_u, count_v, irq_u, irq_v, elapsed_ms;
    uint32_t adc_error_u, adc_error_v, crc32, restored;
    uint16_t min_u, max_u, min_v, max_v;
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
    uint32_t count_w;
    uint16_t min_w, max_w;
#endif
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
    uint32_t irq_w, adc_error_w;
#if defined(ADC_DMA_PARALLEL_LONG_SAMPLE)
    uint32_t sampling_checked_mask;
#endif
#endif
} AdcDmaDiagStatus;
void AdcDmaDiag_Init(ADC_HandleTypeDef *u, ADC_HandleTypeDef *v,
                     uint8_t (*locked)(void));
int AdcDmaDiag_Start(uint32_t now);
int AdcDmaDiag_Busy(void);
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
int AdcDmaDiag_ParallelReady(void);
#endif
void AdcDmaDiag_Service(uint32_t now);
void AdcDmaDiag_Complete(ADC_HandleTypeDef *adc);
void AdcDmaDiag_Error(ADC_HandleTypeDef *adc);
void AdcDmaDiag_Snapshot(AdcDmaDiagStatus *status);
int AdcDmaDiag_Read(uint32_t index, uint16_t *u, uint16_t *v);
#if defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
int AdcDmaDiag_ReadThreePhase(uint32_t index, uint16_t *u, uint16_t *v, uint16_t *w);
#endif
#endif
