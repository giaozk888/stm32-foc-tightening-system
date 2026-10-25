#ifndef ADC_RAW_REPORT_H
#define ADC_RAW_REPORT_H
#include <stddef.h>
#include <stdint.h>
typedef struct {
    uint16_t min_u, max_u, min_v, max_v;
    uint32_t crc32;
} AdcRawReport;
/* CRC32/ISO-HDLC over each pair's U-low,U-high,V-low,V-high bytes. */
int AdcRaw_Summarize(const uint16_t *u, const uint16_t *v, size_t count,
                     AdcRawReport *report);
typedef struct {
    uint16_t min_u, max_u, min_v, max_v, min_w, max_w;
    uint32_t crc32;
} AdcRawThreePhaseReport;
/* ADC1 DMA layout is U0,W0,U1,W1,...; ADC2 is V0,V1,... .
 * Export CRC is logical little-endian U,V,W triples, NOT physical DMA order.
 * W is a later ADC1 rank: this is not three simultaneous sample-and-holds. */
int AdcRaw_SummarizeThreePhase(const uint16_t *uw, const uint16_t *v,
                              size_t count, AdcRawThreePhaseReport *report);
/* Three independent arrays; CRC uses the same logical U,V,W byte order. */
int AdcRaw_SummarizeParallel(const uint16_t *u, const uint16_t *v, const uint16_t *w,
                            size_t count, AdcRawThreePhaseReport *report);
/* Only U/V are measured. W=0 is explicit export padding, not a sample.
 * Preserve the logical U,V,0 CRC without allocating an unused W array. */
int AdcRaw_SummarizeUvPadding(const uint16_t *u, const uint16_t *v,
                            size_t count, AdcRawThreePhaseReport *report);
#endif
