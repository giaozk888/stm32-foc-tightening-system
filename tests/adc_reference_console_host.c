/* Compile the actual reference console; no peripheral or serial IO. */
#include <assert.h>
#include <ctype.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define ADC_DMA_THREE_PHASE_DIAGNOSTIC
#define ADC_DMA_PARALLEL_DIAGNOSTIC
#define ADC_DMA_PARALLEL_LONG_SAMPLE
#define ADC_DMA_ADC12_ONLY_DIAGNOSTIC
#define ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC
#include "../firmware_common/adc_dma_diag.h"
enum { ZERO_ADC_ACQUIRE_ZERO, ZERO_ADC_ACQUIRE_DMA,
       ZERO_ADC_ACQUIRE_REFERENCE_OFF, ZERO_ADC_ACQUIRE_REFERENCE_ON };
enum { PROTO_ERR_BAD_ARGUMENT, PROTO_ERR_NOT_READY, PROTO_ERR_BUSY };
TIM_TypeDef mock_tim;
GPIO_TypeDef mock_gpio;
static unsigned zero_retest_running, foc_control_count, zero_reference_power_kind;
static uint32_t zero_reference_admit_mv;
static unsigned submitted, submit_kind, errors;
static char output[600];
static AdcDmaDiagStatus snapshot;
static uint8_t ZeroRetest_Locked(void) { return 1U; }
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
static uint8_t AdcControlPins_ConfigLow(void) { return 1U; }
static uint8_t AdcControlPins_LevelLow(void) { return 1U; }
#endif
int AdcDmaDiag_ParallelReady(void) { return 1; }
int AdcDmaDiag_Busy(void) { return 0; }
void AdcDmaDiag_Snapshot(AdcDmaDiagStatus *s) { *s = snapshot; }
int AdcDmaDiag_ReadThreePhase(uint32_t i, uint16_t *u, uint16_t *v, uint16_t *w)
{ assert(i < ADC_DMA_DIAG_PAIRS); *u = *v = 2048U; *w = 0U; return 1; }
static void ZeroRetest_SubmitAcquisition(uint32_t id, uint8_t kind)
{ assert(id == 33U); ++submitted; submit_kind = kind; }
static void Protocol_SendError(uint32_t id, unsigned code, const char *name)
{ (void)id; (void)code; ++errors; (void)snprintf(output, sizeof(output), "%s", name); }
static uint8_t Protocol_SendFormatted(char *buffer, size_t capacity, const char *format, ...)
{
    va_list args; va_start(args, format);
    int n = vsnprintf(buffer, capacity, format, args); va_end(args);
    assert(n >= 0 && (size_t)n < capacity && capacity <= sizeof(output));
    memcpy(output, buffer, (size_t)n + 1U); return 1U;
}
#include "../firmware_common/adc_parallel_console.inc"

int main(int argc, char **argv)
{
    assert(argc == 2);
    unsigned n = (unsigned)strtoul(argv[1], NULL, 10);
    if (n == 0U) {
        assert(ZeroRetest_DmaCommand(33U, "ADC PAR SAMPLE"));
        assert(errors == 1U && !submitted && strstr(output, "SELECT_POWER_OFF_OR_ON"));
    } else if (n == 1U || n == 2U) {
        assert(ZeroRetest_DmaCommand(33U, n == 1U ? "ADC PAR SAMPLE OFF" : "ADC PAR SAMPLE ON"));
        assert(submitted == 1U && !errors);
        assert(submit_kind == (n == 1U ? ZERO_ADC_ACQUIRE_REFERENCE_OFF : ZERO_ADC_ACQUIRE_REFERENCE_ON));
    } else if (n == 3U) {
        ZeroRetest_DmaFormat(UINT32_MAX);
        assert(strstr(output, "MODE=ADC12_REFERENCE") && strstr(output, "POWER=NONE ADMIT_MV=0"));
    } else if (n == 4U || n == 5U) {
        snapshot.state = ADC_DMA_DIAG_READY; snapshot.count_u = snapshot.count_v = ADC_DMA_DIAG_PAIRS;
        snapshot.irq_u = snapshot.irq_v = 1U; snapshot.restored = 1U;
        snapshot.sampling_checked_mask = 3U; snapshot.max_u = snapshot.max_v = 4095U;
        snapshot.crc32 = UINT32_MAX; snapshot.elapsed_ms = 999U;
        zero_reference_power_kind = n == 4U ? ZERO_ADC_ACQUIRE_REFERENCE_OFF : ZERO_ADC_ACQUIRE_REFERENCE_ON;
        zero_reference_admit_mv = n == 4U ? 1000U : 14000U;
        ZeroRetest_DmaFormat(UINT32_MAX);
        assert(strstr(output, "SUPPLY_POLICY=EXPLICIT_OFF_ON"));
        assert(strstr(output, n == 4U ? "POWER=OFF ADMIT_MV=1000" : "POWER=ON ADMIT_MV=14000"));
#if defined(ADC_DMA_REFERENCE_DOUBLE_CAPTURE)
        assert(strstr(output, "NU=8192 NV=8192 NW=0"));
        assert(strstr(output, "WINDOW=DOUBLE RAW_STORAGE=UV_ONLY"));
#else
        assert(strstr(output, "NU=4096 NV=4096 NW=0"));
#endif
#if defined(ADC_CONTROL_PINS_LOW_DIAGNOSTIC)
        assert(strstr(output, "PIN_POLICY=GPIO_LOW PIN_CFG=1 PIN_LEVEL=1") && strlen(output) < 560U);
#else
        assert(strlen(output) < 480U);
#endif
    } else if (n == 6U) {
        assert(!ZeroRetest_DmaCommand(33U, "ADC PAR SAMPLE ON extra"));
        assert(!submitted && !errors);
    } else if (n == 8U) {
        char command[40];
        snprintf(command, sizeof(command), "ADC PAR READ %u", ADC_DMA_DIAG_PAIRS-8U);
        assert(ZeroRetest_DmaCommand(33U, command));
        assert(!errors && strstr(output, "N=8 UVW=080008000000"));
    } else if (n == 9U) {
        char command[40];
        snprintf(command, sizeof(command), "ADC PAR READ %u", ADC_DMA_DIAG_PAIRS);
        assert(ZeroRetest_DmaCommand(33U, command));
        assert(errors && strstr(output, "READ_INDEX"));
    } else {
        assert(ZeroRetest_DmaCommand(33U, "ADC PAR READ 0"));
        assert(strstr(output, "I=0 N=8 UVW=080008000000"));
    }
    puts(output);
    return 0;
}
