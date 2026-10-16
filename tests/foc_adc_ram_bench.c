/* Isolated digital bench, NOT a motor-control/analog qualification image.
 * Executes the actual window planner, CCR commit and timing adapter in SRAM.
 * Only ADC1_2 IRQ is enabled; no scheduler, normal startup or FOC current loop.
 * The host validates existing clocks/ADC configuration and restores context.
 * LOW_SIDE_UV here is a geometry TEST INPUT, not a claimed sensor topology.
 */
#include "main.h"
#include "foc_adc_timing_stm32.h"
#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint32_t index, mode, phase[3], trigger, elapsed_us, elapsed_cycles;
    uint32_t irq_entries, pairs, pair_misses, deadline_misses;
    uint32_t max_cycles, last_cycles, plan_failures, plan_updates, blocks;
    uint32_t raw_count, raw_sum[2], raw_ss[2], raw_min[2], raw_max[2], raw_step[2];
    uint32_t mixed_block, slack, miss_adc1_flags, miss_adc2_flags;
} BenchCase;
typedef struct {
    uint32_t magic, state, current_case, total_cases, case_us, fault, sd_high_seen;
    uint32_t irq_count, cfsr, adc_error_flags, reserved[6];
    BenchCase cases[8];
} BenchReport;
_Static_assert(sizeof(BenchCase) == 128, "Host layout");
_Static_assert(offsetof(BenchReport, cases) == 64, "Host layout");

volatile BenchReport foc_bench_report;
/* Set by the host AFTER image loading and BEFORE execution. */
volatile uint32_t foc_bench_case_us = 200000;
__attribute__((section(".data.bench_input"))) volatile uint32_t foc_bench_single_95;
static volatile uint32_t handler_max, handler_last, miss1, miss2;
extern uint32_t __bench_bss_start, __bench_bss_end, __bench_stack_top;
void foc_bench_entry(void);
static void bench_fault(void);
static void bench_adc_irq(void);

/* Small freestanding libc subset; no allocation or Flash-resident library. */
void *memset(void *dst, int value, size_t n)
{
    unsigned char *p = dst;
    for (size_t i = 0; i < n; ++i) p[i] = (unsigned char)value;
    return dst;
}
void *memcpy(void *dst, const void *src, size_t n)
{
    unsigned char *d = dst; const unsigned char *s = src;
    for (size_t i = 0; i < n; ++i) d[i] = s[i];
    return dst;
}
int memcmp(const void *a, const void *b, size_t n)
{
    const unsigned char *x = a, *y = b;
    for (size_t i = 0; i < n; ++i) if (x[i] != y[i]) return (int)x[i] - y[i];
    return 0;
}

__attribute__((section(".vectors"), used))
const uintptr_t bench_vectors[128] = {
    [0 ... 127] = (uintptr_t)bench_fault,
    [0] = (uintptr_t)&__bench_stack_top,
    [1] = (uintptr_t)foc_bench_entry,
    [16 + ADC1_2_IRQn] = (uintptr_t)bench_adc_irq,
};

/* No RCC mutation. Frequencies are preflight-validated by the host. */
uint32_t HAL_RCC_GetHCLKFreq(void) { return 170000000U; }
uint32_t HAL_RCC_GetPCLK2Freq(void) { return 170000000U; }
uint32_t HAL_RCC_GetSysClockFreq(void) { return 170000000U; }

static void off(void)
{
    GPIOC->BSRR = GPIO_PIN_6 << 16;
    TIM1->BDTR &= ~TIM_BDTR_MOE;
    TIM1->CCER = 0;
    TIM1->CR1 &= ~TIM_CR1_CEN;
    ADC1->IER = ADC2->IER = 0;
}
__attribute__((noreturn)) static void finish(void)
{
    __disable_irq();
    off();
    foc_bench_report.cfsr = SCB->CFSR;
    __DSB(); __BKPT(0);
    for (;;) { off(); }
}
static void bench_fault(void)
{
    foc_bench_report.fault = 0xF0000000U | __get_IPSR();
    foc_bench_report.state = 3;
    finish();
}
static void bench_adc_irq(void)
{
    uint32_t whole_start = DWT->CYCCNT;
    uint32_t start = FocAdcTiming_IrqEnter();
    ++foc_bench_report.irq_count;
    GPIOC->BSRR = GPIO_PIN_6 << 16;
    uint32_t errors = (ADC1->ISR | ADC2->ISR) & (ADC_ISR_OVR | ADC_ISR_JQOVF);
    if (errors) {
        foc_bench_report.adc_error_flags |= errors;
        foc_bench_report.fault = 6;
        off();
    } else if (!FocAdcTiming_PairReady()) {
        miss1 = ADC1->ISR; miss2 = ADC2->ISR;
        foc_bench_report.fault = 1;
        off();
    } else {
        uint16_t u = (uint16_t)ADC1->JDR1;
        uint16_t v = (uint16_t)ADC2->JDR1;
        ADC1->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
        ADC2->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
        FocAdcTiming_RecordRaw(u, v);
    }
    FocAdcTiming_IrqExit(start);
    handler_last = DWT->CYCCNT - whole_start;
    if (handler_last > handler_max) handler_max = handler_last;
}

static void save_case(unsigned idx, unsigned mode, uint32_t us, uint32_t cycles,
                      const FocAdcTimingSnapshot *before)
{
    FocAdcTimingSnapshot s;
    /* Timer is stopped here; flush at most the two completed diagnostic blocks. */
    (void)FocAdcTiming_ProcessRawOne();
    (void)FocAdcTiming_ProcessRawOne();
    FocAdcTiming_Snapshot(&s);
    volatile BenchCase *r = &foc_bench_report.cases[idx];
    r->index = idx; r->mode = mode;
    r->phase[0] = TIM1->CCR1; r->phase[1] = TIM1->CCR2; r->phase[2] = TIM1->CCR3;
    r->trigger = TIM1->CCR4;
    r->elapsed_us = us; r->elapsed_cycles = cycles;
    r->irq_entries = s.irq_entries - before->irq_entries;
    r->pairs = s.pairs - before->pairs;
    r->pair_misses = s.pair_misses - before->pair_misses;
    r->deadline_misses = s.deadline_misses - before->deadline_misses;
    r->max_cycles = handler_max; r->last_cycles = handler_last;
    r->plan_failures = s.plan_failures - before->plan_failures;
    r->plan_updates = s.plan_sequence - before->plan_sequence;
    r->blocks = s.processed_blocks - before->processed_blocks;
    r->raw_count = s.raw.count;
    for (unsigned ch = 0; ch < 2; ++ch) {
        r->raw_sum[ch] = s.raw.sum[ch]; r->raw_ss[ch] = s.raw.sum_sq[ch];
        r->raw_min[ch] = s.raw.min[ch]; r->raw_max[ch] = s.raw.max[ch];
        r->raw_step[ch] = s.raw.max_step[ch];
    }
    r->mixed_block = s.mixed_block; r->slack = s.slack_ticks;
    r->miss_adc1_flags = miss1; r->miss_adc2_flags = miss2;
}

void foc_bench_entry(void)
{
    __disable_irq();
    for (uint32_t *p = &__bench_bss_start; p < &__bench_bss_end; ++p) *p = 0;
    off();
    uint32_t duration = foc_bench_case_us;
    if (duration < 100000 || duration > 10000000) duration = 200000;
    /* Either seven finite cases or one 95%-reference capture window. */
    unsigned total = foc_bench_single_95 ? 1 : 7;
    foc_bench_report.magic = 0x464F4342;
    foc_bench_report.case_us = duration;
    foc_bench_report.total_cases = total;
    for (unsigned idx = 0; idx < total; ++idx) {
        unsigned mode = foc_bench_single_95 ? 4 : idx;
        FocAdcTimingSnapshot before;
        FocAdcTiming_Snapshot(&before);
        handler_max = handler_last = miss1 = miss2 = 0;
        float duty = mode == 2 ? .80f : mode == 3 ? .90f : mode >= 4 ? .95f : .50f;
        float v = mode == 5 ? .90f : duty;
        float w = mode == 5 ? .80f : duty;
        if (FocAdcTiming_Commit(duty, v, w) != FOC_WINDOW_OK || !FocAdcTiming_CanStart()) {
            foc_bench_report.fault = 2; break;
        }
        if (mode == 0) {
            TIM1->CCR4 = 3500; /* Existing fixed-trigger baseline. */
            TIM1->EGR = TIM_EGR_UG;
        }
        ADC1->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
        ADC2->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
        NVIC_ClearPendingIRQ(ADC1_2_IRQn);
        ADC1->IER = ADC_IER_JEOSIE; /* One shared IRQ; ADC2 never enables JEOS IRQ. */
        TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC1NE | TIM_CCER_CC2E |
                     TIM_CCER_CC2NE | TIM_CCER_CC3E | TIM_CCER_CC3NE | TIM_CCER_CC4E;
        TIM1->SR = 0;
        uint32_t begin_us = TIM2->CNT, begin_cycles = DWT->CYCCNT;
        TIM1->BDTR |= TIM_BDTR_MOE;
        TIM1->CR1 |= TIM_CR1_CEN;
        foc_bench_report.current_case = idx;
        foc_bench_report.state = 1;
        __enable_irq();
        uint32_t update_us = begin_us;
        uint32_t worker_us = begin_us;
        unsigned update = 0;
        while ((uint32_t)(TIM2->CNT - begin_us) < duration &&
               (uint32_t)(DWT->CYCCNT - begin_cycles) < duration * 170U + 17000000U &&
               foc_bench_report.fault == 0) {
            if (GPIOC->ODR & GPIO_PIN_6) {
                ++foc_bench_report.sd_high_seen; foc_bench_report.fault = 3;
            }
            GPIOC->BSRR = GPIO_PIN_6 << 16;
            IWDG->KR = 0xAAAA; /* Refresh only, never enable watchdog. */
            if ((uint32_t)(TIM2->CNT - worker_us) >= 1000U) {
                worker_us = TIM2->CNT;
                (void)FocAdcTiming_ProcessRawOne();
                (void)FocAdcTiming_ProcessRawOne();
            }
            if (mode == 6 && (uint32_t)(TIM2->CNT - update_us) >= 500U) {
                update_us = TIM2->CNT;
                float x = (++update & 1) ? .95f : .50f;
                if (FocAdcTiming_Commit(x, x, x) != FOC_WINDOW_OK) {
                    foc_bench_report.fault = 4; break;
                }
            }
        }
        __disable_irq();
        off();
        uint32_t elapsed = TIM2->CNT - begin_us, cyc = DWT->CYCCNT - begin_cycles;
        save_case(idx, mode, elapsed, cyc, &before);
        if (elapsed < duration && foc_bench_report.fault == 0) foc_bench_report.fault = 5;
        /* Let a conversion already in flight finish with IRQs disabled. */
        uint32_t quiet = TIM2->CNT;
        while ((uint32_t)(TIM2->CNT - quiet) < 20U) GPIOC->BSRR = GPIO_PIN_6 << 16;
        ADC1->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
        ADC2->ISR = ADC_ISR_JEOC | ADC_ISR_JEOS;
        if (foc_bench_report.fault) break;
    }
    FocAdcTimingSnapshot final;
    FocAdcTiming_Snapshot(&final);
    foc_bench_report.reserved[0] = final.dropped_blocks;
    foc_bench_report.reserved[1] = final.dropped_samples;
    foc_bench_report.reserved[2] = final.processed_blocks;
    foc_bench_report.state = foc_bench_report.fault ? 3 : 2;
    finish();
}
